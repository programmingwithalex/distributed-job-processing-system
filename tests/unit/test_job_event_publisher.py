from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.common.models.job_event_outbox import JobEventOutboxRecord
from app.worker.outbox_publisher import (
    build_pending_outbox_statement,
    calculate_outbox_retry_delay_seconds,
    ensure_job_events_topic,
    publish_pending_job_events,
)


class FakeKafkaProducer:
    """Record messages and immediately invoke delivery callbacks for tests."""

    def __init__(self, delivery_error: str | None = None, pending_message_count: int = 0) -> None:
        """Initialize producer outcomes used by publisher tests."""
        self.delivery_error = delivery_error
        self.pending_message_count = pending_message_count
        self.produced_messages: list[dict[str, object]] = []
        self.partition_number = 2
        self.kafka_offset = 10

    def produce(self, **message: object) -> None:
        """Capture one message and invoke its delivery callback."""
        self.produced_messages.append(message)
        callback = message["on_delivery"]
        callback(
            self.delivery_error,
            SimpleNamespace(
                partition=lambda: self.partition_number,
                offset=lambda: self.kafka_offset,
            ),
        )

    def poll(self, _timeout: float) -> None:
        """Provide the producer polling method used for a full local queue."""

    def flush(self, timeout: float) -> int:
        """Return the configured count of messages still awaiting delivery."""
        return self.pending_message_count


def build_outbox_record() -> JobEventOutboxRecord:
    """Create a pending outbox event for publisher tests."""
    job_id = uuid4()
    event_id = uuid4()
    return JobEventOutboxRecord(
        event_id=event_id,
        job_id=job_id,
        sequence_number=1,
        topic="job-events.v1",
        message_key=str(job_id),
        event_type="submitted",
        payload={"event_id": str(event_id), "job_id": str(job_id)},
        publish_attempt_count=0,
    )


def test_calculate_outbox_retry_delay_uses_capped_exponential_backoff() -> None:
    """Verify publisher retries slow down and stop at the configured cap."""
    assert calculate_outbox_retry_delay_seconds(publish_attempt_count=1) == 1
    assert calculate_outbox_retry_delay_seconds(publish_attempt_count=2) == 2
    assert calculate_outbox_retry_delay_seconds(publish_attempt_count=3) == 4
    assert calculate_outbox_retry_delay_seconds(publish_attempt_count=20) == 300


def test_ensure_job_events_topic_creates_partitioned_lifecycle_topic() -> None:
    """Verify startup provisions the versioned topic with the configured partitions."""
    admin_client = MagicMock()
    admin_client.create_topics.return_value = {"job-events.v1": MagicMock()}

    ensure_job_events_topic(admin_client=admin_client)

    created_topics = admin_client.create_topics.call_args.args[0]
    assert len(created_topics) == 1
    assert created_topics[0].topic == "job-events.v1"
    assert created_topics[0].num_partitions == 3
    assert created_topics[0].replication_factor == 1
    admin_client.create_topics.return_value["job-events.v1"].result.assert_called_once_with()


def test_build_pending_outbox_statement_preserves_per_job_event_order() -> None:
    """Verify a later pending event cannot pass an earlier unpublished event."""
    outbox_statement = build_pending_outbox_statement(
        current_time=datetime.now(UTC),
        batch_size=25,
    )
    compiled_statement = str(
        outbox_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "NOT (EXISTS" in compiled_statement
    assert "sequence_number" in compiled_statement
    assert "FOR UPDATE SKIP LOCKED" in compiled_statement


def test_publish_pending_job_events_marks_delivery_acknowledged_by_kafka() -> None:
    """Verify the outbox is marked published only after its delivery callback succeeds."""
    database_session = MagicMock()
    outbox_record = build_outbox_record()
    database_session.execute.return_value.scalars.return_value.all.return_value = [outbox_record]
    producer = FakeKafkaProducer()
    publication_time = datetime.now(UTC)

    published_count = publish_pending_job_events(
        database_session=database_session,
        producer=producer,
        current_time=publication_time,
        batch_size=1,
        delivery_timeout_seconds=2.0,
    )

    assert published_count == 1
    assert outbox_record.published_at == publication_time
    assert outbox_record.publish_attempt_count == 1
    assert outbox_record.next_attempt_at is None
    assert outbox_record.last_error is None
    assert producer.produced_messages[0]["topic"] == "job-events.v1"
    assert producer.produced_messages[0]["key"] == str(outbox_record.job_id)
    assert database_session.execute.call_count == 2
    database_session.commit.assert_called_once_with()


def test_publish_pending_job_events_schedules_retry_after_delivery_error() -> None:
    """Verify Kafka delivery errors retain the outbox row and schedule a retry."""
    database_session = MagicMock()
    outbox_record = build_outbox_record()
    database_session.execute.return_value.scalars.return_value.all.return_value = [outbox_record]
    producer = FakeKafkaProducer(delivery_error="broker unavailable")
    publication_time = datetime.now(UTC)

    published_count = publish_pending_job_events(
        database_session=database_session,
        producer=producer,
        current_time=publication_time,
        batch_size=1,
        delivery_timeout_seconds=2.0,
    )

    assert published_count == 0
    assert outbox_record.published_at is None
    assert outbox_record.publish_attempt_count == 1
    assert outbox_record.next_attempt_at == publication_time + timedelta(seconds=1)
    assert outbox_record.last_error == "broker unavailable"
    database_session.commit.assert_called_once_with()