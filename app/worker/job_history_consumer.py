from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.orm import Session

from app.common.config import get_application_settings
from app.common.database import database_session_factory
from app.common.schemas.job_events import JobLifecycleEvent
from app.common.services.job_history import (
    clear_job_history_projection,
    persist_job_history_event,
)

if TYPE_CHECKING:
    from confluent_kafka import Consumer, Message

logger = logging.getLogger(__name__)
KAFKA_POLL_TIMEOUT_SECONDS = 1.0
KAFKA_METADATA_TIMEOUT_SECONDS = 10.0


def parse_job_event_message(message: Message) -> JobLifecycleEvent:
    """Validate a Kafka message and confirm its key matches the event job ID.

    Args:
        message: Kafka record received from the lifecycle topic

    Returns:
        Validated versioned lifecycle event

    Raises:
        TypeError: Raised when the record has no job ID key
        ValueError: Raised when the record has no payload or a mismatched key
    """
    message_value = message.value()
    if message_value is None:
        raise ValueError("Kafka job event has an empty payload")

    job_lifecycle_event = JobLifecycleEvent.model_validate_json(message_value)
    message_key = message.key()
    if isinstance(message_key, bytes):
        decoded_message_key = message_key.decode("utf-8")
    elif isinstance(message_key, str):
        decoded_message_key = message_key
    else:
        raise TypeError("Kafka job event key must contain a job ID")

    if decoded_message_key != str(job_lifecycle_event.job_id):
        raise ValueError("Kafka job event key does not match its job ID")

    return job_lifecycle_event


def persist_kafka_message_to_history(
    message: Message,
    session_factory: Callable[[], Session],
) -> bool:
    """Persist one Kafka message to the idempotent history projection.

    Args:
        message: Kafka record received from the lifecycle topic
        session_factory: Factory for independent database sessions

    Returns:
        True when the event was inserted, otherwise False for a duplicate
    """
    job_lifecycle_event = parse_job_event_message(message=message)
    database_session = session_factory()
    try:
        return persist_job_history_event(
            database_session=database_session,
            job_lifecycle_event=job_lifecycle_event,
            source_topic=message.topic(),
            partition_number=message.partition(),
            kafka_offset=message.offset(),
        )
    except Exception:
        database_session.rollback()
        raise
    finally:
        database_session.close()


def process_job_event_message(
    message: Message,
    consumer: Consumer,
    session_factory: Callable[[], Session],
) -> bool:
    """Persist one event before committing its Kafka consumer offset.

    Args:
        message: Kafka record received from the lifecycle topic
        consumer: Kafka consumer whose offset follows the record
        session_factory: Factory for independent database sessions

    Returns:
        True when the event was newly inserted, otherwise False for a duplicate
    """
    event_was_inserted = persist_kafka_message_to_history(
        message=message,
        session_factory=session_factory,
    )
    consumer.commit(message=message, asynchronous=False)
    return event_was_inserted


def build_kafka_consumer(group_id: str | None = None) -> Consumer:
    """Create a manually committed consumer for the job history projection.

    Args:
        group_id: Optional override for replaying the topic from its beginning

    Returns:
        Configured Kafka consumer
    """
    from confluent_kafka import Consumer

    application_settings = get_application_settings()
    return Consumer(
        {
            "bootstrap.servers": application_settings.kafka_bootstrap_servers,
            "group.id": group_id or application_settings.job_history_consumer_group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
        }
    )


def main() -> None:
    """Consume job lifecycle events and maintain the PostgreSQL history projection."""
    from confluent_kafka import KafkaError, KafkaException

    application_settings = get_application_settings()
    kafka_consumer = build_kafka_consumer()
    kafka_consumer.subscribe([application_settings.job_events_topic])
    logger.info(
        "Started job history consumer for topic %s with group %s",
        application_settings.job_events_topic,
        application_settings.job_history_consumer_group,
    )
    try:
        while True:
            kafka_message = kafka_consumer.poll(KAFKA_POLL_TIMEOUT_SECONDS)
            if kafka_message is None:
                continue
            kafka_error = kafka_message.error()
            if kafka_error is not None:
                if kafka_error.code() == KafkaError._PARTITION_EOF:
                    continue
                if kafka_error.code() == KafkaError.UNKNOWN_TOPIC_OR_PART:
                    logger.info(
                        "Waiting for Kafka topic %s to become available",
                        application_settings.job_events_topic,
                    )
                    continue
                raise KafkaException(kafka_error)

            process_job_event_message(
                message=kafka_message,
                consumer=kafka_consumer,
                session_factory=database_session_factory,
            )
    finally:
        kafka_consumer.close()


def rebuild_main() -> None:
    """Rebuild projected history from retained Kafka events without running jobs."""
    from confluent_kafka import KafkaError, KafkaException, TopicPartition

    application_settings = get_application_settings()
    kafka_consumer = build_kafka_consumer(group_id=f"job-history-rebuild-{uuid4()}")
    try:
        topic_metadata = kafka_consumer.list_topics(
            application_settings.job_events_topic,
            timeout=KAFKA_METADATA_TIMEOUT_SECONDS,
        )
        topic_information = topic_metadata.topics.get(application_settings.job_events_topic)
        if topic_information is None or topic_information.error is not None:
            raise RuntimeError(
                f"Kafka topic {application_settings.job_events_topic} is unavailable"
            )

        start_offsets: dict[int, int] = {}
        end_offsets: dict[int, int] = {}
        for partition_number in topic_information.partitions:
            topic_partition = TopicPartition(
                application_settings.job_events_topic,
                partition_number,
            )
            low_watermark, high_watermark = kafka_consumer.get_watermark_offsets(
                topic_partition,
                timeout=KAFKA_METADATA_TIMEOUT_SECONDS,
                cached=False,
            )
            if low_watermark != 0:
                raise RuntimeError(
                    "Kafka retention has removed earlier job events; history cannot be fully rebuilt"
                )
            start_offsets[partition_number] = low_watermark
            end_offsets[partition_number] = high_watermark

        if not start_offsets:
            raise RuntimeError(
                f"Kafka topic {application_settings.job_events_topic} has no partitions"
            )

        database_session = database_session_factory()
        try:
            clear_job_history_projection(database_session=database_session)
        finally:
            database_session.close()

        kafka_consumer.assign(
            [
                TopicPartition(
                    application_settings.job_events_topic,
                    partition_number,
                    start_offset,
                )
                for partition_number, start_offset in start_offsets.items()
            ]
        )
        consumed_offsets = dict(start_offsets)
        rebuilt_event_count = 0
        while any(
            consumed_offsets[partition_number] < end_offset
            for partition_number, end_offset in end_offsets.items()
        ):
            kafka_message = kafka_consumer.poll(KAFKA_POLL_TIMEOUT_SECONDS)
            if kafka_message is None:
                continue
            kafka_error = kafka_message.error()
            if kafka_error is not None:
                if kafka_error.code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(kafka_error)

            partition_number = kafka_message.partition()
            if kafka_message.offset() >= end_offsets[partition_number]:
                continue

            if persist_kafka_message_to_history(
                message=kafka_message,
                session_factory=database_session_factory,
            ):
                rebuilt_event_count += 1
            consumed_offsets[partition_number] = max(
                consumed_offsets[partition_number],
                kafka_message.offset() + 1,
            )

        logger.info("Rebuilt job history from %s Kafka events", rebuilt_event_count)
    finally:
        kafka_consumer.close()