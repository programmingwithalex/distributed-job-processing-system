from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.common.config import get_application_settings
from app.common.database import database_session_factory
from app.common.models.job_event_outbox import JobEventOutboxRecord
from app.common.services.job_event_offsets import record_job_event_partition_offset

if TYPE_CHECKING:
    from confluent_kafka import KafkaError, Message, Producer

MAXIMUM_RETRY_DELAY_SECONDS = 300
PRODUCER_QUEUE_POLL_SECONDS = 1.0
KAFKA_METADATA_TIMEOUT_SECONDS = 10.0
logger = logging.getLogger(__name__)


def build_delivery_callback(
    delivery_errors: list[str],
    delivery_offsets: list[tuple[int, int]],
) -> Callable[[KafkaError | None, Message], None]:
    """Bind one outbox event's delivery result collections to its callback.

    Args:
        delivery_errors: Errors reported for this delivery
        delivery_offsets: Kafka partition and offset acknowledged for this delivery

    Returns:
        Delivery callback bound to this event's result collections
    """
    def on_delivery(error: KafkaError | None, message: Message) -> None:
        if error is not None:
            delivery_errors.append(str(error))
        else:
            delivery_offsets.append((message.partition(), message.offset()))

    return on_delivery


def calculate_outbox_retry_delay_seconds(publish_attempt_count: int) -> int:
    """Return a capped exponential delay before retrying a failed event.

    Args:
        publish_attempt_count: Number of delivery attempts made for the event

    Returns:
        Delay in seconds before the next attempt
    """
    exponent = max(publish_attempt_count - 1, 0)
    return min(2**exponent, MAXIMUM_RETRY_DELAY_SECONDS)


def build_pending_outbox_statement(
    current_time: datetime,
    batch_size: int,
) -> select[tuple[JobEventOutboxRecord]]:
    """Select due outbox rows without allowing later events for a job to pass.

    Args:
        current_time: Timestamp used to determine whether retries are due
        batch_size: Maximum number of events to claim

    Returns:
        Locking statement for due head-of-line events
    """
    earlier_outbox_record = aliased(JobEventOutboxRecord)
    earlier_event_exists = exists(
        select(earlier_outbox_record.event_id).where(
            earlier_outbox_record.job_id == JobEventOutboxRecord.job_id,
            earlier_outbox_record.published_at.is_(None),
            earlier_outbox_record.sequence_number < JobEventOutboxRecord.sequence_number,
        )
    )
    return (
        select(JobEventOutboxRecord)
        .where(
            JobEventOutboxRecord.published_at.is_(None),
            or_(
                JobEventOutboxRecord.next_attempt_at.is_(None),
                JobEventOutboxRecord.next_attempt_at <= current_time,
            ),
            ~earlier_event_exists,
        )
        .order_by(JobEventOutboxRecord.created_at, JobEventOutboxRecord.event_id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )


def publish_pending_job_events(
    database_session: Session,
    producer: Producer,
    *,
    current_time: datetime | None = None,
    batch_size: int | None = None,
    delivery_timeout_seconds: float | None = None,
) -> int:
    """Publish due outbox rows and persist delivery outcomes.

    The database lock is held through the bounded Kafka delivery wait. A crash
    after Kafka acknowledges delivery but before commit can resend the same event;
    consumers use the stable event ID to deduplicate that at-least-once delivery.

    Args:
        database_session: Session used to claim rows and store delivery outcomes
        producer: Kafka producer configured for the event broker
        current_time: Optional timestamp for deterministic retry tests
        batch_size: Optional maximum number of events to claim
        delivery_timeout_seconds: Optional maximum wait for each delivery callback

    Returns:
        Number of events acknowledged by Kafka in this batch
    """
    application_settings = get_application_settings()
    publication_time = current_time or datetime.now(UTC)
    effective_batch_size = batch_size or application_settings.job_event_publisher_batch_size
    effective_delivery_timeout = (
        delivery_timeout_seconds or application_settings.job_event_delivery_timeout_seconds
    )
    outbox_statement = build_pending_outbox_statement(
        current_time=publication_time,
        batch_size=effective_batch_size,
    )
    outbox_records = database_session.execute(outbox_statement).scalars().all()
    if not outbox_records:
        return 0

    published_count = 0
    for outbox_record in outbox_records:
        outbox_record.publish_attempt_count += 1
        delivery_errors: list[str] = []
        delivery_offsets: list[tuple[int, int]] = []
        on_delivery = build_delivery_callback(
            delivery_errors=delivery_errors,
            delivery_offsets=delivery_offsets,
        )

        try:
            try:
                producer.produce(
                    topic=outbox_record.topic,
                    key=outbox_record.message_key,
                    value=json.dumps(outbox_record.payload, separators=(",", ":")),
                    on_delivery=on_delivery,
                )
            except BufferError:
                producer.poll(PRODUCER_QUEUE_POLL_SECONDS)
                producer.produce(
                    topic=outbox_record.topic,
                    key=outbox_record.message_key,
                    value=json.dumps(outbox_record.payload, separators=(",", ":")),
                    on_delivery=on_delivery,
                )

            pending_message_count = producer.flush(timeout=effective_delivery_timeout)
            if pending_message_count > 0:
                raise TimeoutError("Kafka delivery callback timed out")
            if delivery_errors:
                raise RuntimeError(delivery_errors[0])
            if not delivery_offsets:
                raise RuntimeError("Kafka delivery callback returned no partition offset")
        except (BufferError, KafkaException, RuntimeError, TimeoutError) as publish_error:
            outbox_record.last_error = str(publish_error)[:1000]
            outbox_record.next_attempt_at = publication_time + timedelta(
                seconds=calculate_outbox_retry_delay_seconds(
                    publish_attempt_count=outbox_record.publish_attempt_count,
                )
            )
            logger.warning(
                "Kafka publish failed for event %s; retrying after %s seconds: %s",
                outbox_record.event_id,
                calculate_outbox_retry_delay_seconds(
                    publish_attempt_count=outbox_record.publish_attempt_count,
                ),
                outbox_record.last_error,
            )
            continue

        partition_number, kafka_offset = delivery_offsets[-1]
        record_job_event_partition_offset(
            database_session=database_session,
            topic=outbox_record.topic,
            partition_number=partition_number,
            offset=kafka_offset,
            offset_kind="published",
        )
        outbox_record.published_at = publication_time
        outbox_record.next_attempt_at = None
        outbox_record.last_error = None
        published_count += 1

    database_session.commit()
    return published_count


def build_kafka_producer() -> Producer:
    """Create an idempotent Kafka producer for job lifecycle events.

    Returns:
        Configured Kafka producer
    """
    from confluent_kafka import Producer

    application_settings = get_application_settings()
    return Producer(
        {
            "bootstrap.servers": application_settings.kafka_bootstrap_servers,
            "client.id": "job-event-outbox-publisher",
            "enable.idempotence": True,
            "acks": "all",
            "message.timeout.ms": int(
                application_settings.job_event_delivery_timeout_seconds * 1000
            ),
        }
    )


def ensure_job_events_topic(admin_client: AdminClient | None = None) -> None:
    """Create the configured lifecycle topic before the publisher starts.

    Args:
        admin_client: Optional Kafka admin client used for dependency injection

    Raises:
        KafkaException: Raised when topic creation fails for a reason other than
            the topic already existing
    """
    application_settings = get_application_settings()
    active_admin_client = admin_client or AdminClient(
        {"bootstrap.servers": application_settings.kafka_bootstrap_servers}
    )
    topic_creation_futures = active_admin_client.create_topics(
        [
            NewTopic(
                application_settings.job_events_topic,
                num_partitions=application_settings.job_events_partition_count,
                replication_factor=1,
            )
        ],
        operation_timeout=KAFKA_METADATA_TIMEOUT_SECONDS,
        request_timeout=KAFKA_METADATA_TIMEOUT_SECONDS + 5,
    )
    try:
        topic_creation_futures[application_settings.job_events_topic].result()
    except KafkaException as topic_error:
        kafka_error = topic_error.args[0]
        if kafka_error.code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise


def main() -> None:
    """Poll PostgreSQL and publish committed job lifecycle events to Kafka."""
    application_settings = get_application_settings()
    ensure_job_events_topic()
    producer = build_kafka_producer()
    logger.info(
        "Started job event publisher for topic %s on %s",
        application_settings.job_events_topic,
        application_settings.kafka_bootstrap_servers,
    )
    try:
        while True:
            database_session = database_session_factory()
            try:
                published_count = publish_pending_job_events(
                    database_session=database_session,
                    producer=producer,
                )
            except Exception:
                database_session.rollback()
                logger.exception("Job event publisher iteration failed")
                published_count = 0
            finally:
                database_session.close()

            if published_count == 0:
                time.sleep(application_settings.job_event_publisher_poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Stopping job event publisher")
    finally:
        producer.flush(timeout=application_settings.job_event_delivery_timeout_seconds)