import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.common.models.job import JobStatus, JobType
from app.common.schemas.job_events import JobLifecycleEvent, JobLifecycleEventType
from app.common.services.job_history import (
    build_job_history_insert_statement,
    build_job_history_listing_statement,
)
from app.worker.job_history_consumer import process_job_event_message


def build_job_lifecycle_event() -> JobLifecycleEvent:
    """Create a valid typed job lifecycle event for history tests."""
    return JobLifecycleEvent(
        event_type=JobLifecycleEventType.PROCESSING,
        occurred_at=datetime.now(UTC),
        job_id=uuid4(),
        sequence_number=2,
        job_type=JobType.REVERSE,
        status=JobStatus.PROCESSING,
        attempt_count=1,
        maximum_attempt_count=3,
    )


class FakeKafkaMessage:
    """Provide the Kafka message methods used by the projection consumer."""

    def __init__(
        self,
        job_lifecycle_event: JobLifecycleEvent,
        message_key: str | None = None,
    ) -> None:
        """Serialize one event and derive its Kafka key for a consumer test."""
        self.job_lifecycle_event = job_lifecycle_event
        self.message_key = message_key or str(job_lifecycle_event.job_id)
        self.partition_number = 2
        self.kafka_offset = 10

    def value(self) -> bytes:
        """Return the event envelope as UTF-8 JSON bytes."""
        return json.dumps(self.job_lifecycle_event.model_dump(mode="json")).encode("utf-8")

    def key(self) -> bytes:
        """Return the event's job ID Kafka key."""
        return self.message_key.encode("utf-8")

    def topic(self) -> str:
        """Return the Kafka topic containing the test event."""
        return "job-events.v1"

    def partition(self) -> int:
        """Return the Kafka partition containing the test event."""
        return self.partition_number

    def offset(self) -> int:
        """Return the Kafka offset of the test event."""
        return self.kafka_offset


def test_build_job_history_insert_statement_ignores_duplicate_event_ids() -> None:
    """Verify history insertion uses the event ID as its idempotency key."""
    insert_statement = build_job_history_insert_statement(
        job_lifecycle_event=build_job_lifecycle_event()
    )
    compiled_statement = str(
        insert_statement.compile(
            dialect=postgresql.dialect(),
        )
    )

    assert "ON CONFLICT (event_id) DO NOTHING" in compiled_statement


def test_build_job_history_listing_statement_orders_events_by_sequence() -> None:
    """Verify history reads are chronological and support pagination."""
    job_id = uuid4()
    history_statement = build_job_history_listing_statement(
        job_id=job_id,
        limit=20,
        offset=5,
    )
    compiled_statement = str(
        history_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "WHERE job_history.job_id =" in compiled_statement
    assert "ORDER BY job_history.sequence_number" in compiled_statement
    assert " LIMIT 20" in compiled_statement
    assert " OFFSET 5" in compiled_statement


def test_process_job_event_message_commits_database_before_kafka_offset() -> None:
    """Verify the consumer only commits an offset after PostgreSQL succeeds."""
    job_lifecycle_event = build_job_lifecycle_event()
    kafka_message = FakeKafkaMessage(job_lifecycle_event=job_lifecycle_event)
    operation_order: list[str] = []
    database_session = MagicMock()
    database_session.execute.return_value.rowcount = 1
    database_session.commit.side_effect = lambda: operation_order.append("database")
    session_factory = MagicMock(return_value=database_session)
    kafka_consumer = MagicMock()
    kafka_consumer.commit.side_effect = lambda **_kwargs: operation_order.append("kafka")

    inserted = process_job_event_message(
        message=kafka_message,
        consumer=kafka_consumer,
        session_factory=session_factory,
    )

    assert inserted is True
    assert operation_order == ["database", "kafka"]
    kafka_consumer.commit.assert_called_once_with(message=kafka_message, asynchronous=False)
    database_session.close.assert_called_once_with()


def test_process_job_event_message_deduplicates_but_still_commits_offset() -> None:
    """Verify a duplicate event remains safe and does not block its Kafka partition."""
    kafka_message = FakeKafkaMessage(job_lifecycle_event=build_job_lifecycle_event())
    database_session = MagicMock()
    database_session.execute.return_value.rowcount = 0
    kafka_consumer = MagicMock()

    inserted = process_job_event_message(
        message=kafka_message,
        consumer=kafka_consumer,
        session_factory=MagicMock(return_value=database_session),
    )

    assert inserted is False
    database_session.commit.assert_called_once_with()
    kafka_consumer.commit.assert_called_once_with(message=kafka_message, asynchronous=False)


def test_process_job_event_message_rejects_a_mismatched_partition_key() -> None:
    """Verify malformed key/payload pairs are not persisted or offset-committed."""
    kafka_message = FakeKafkaMessage(
        job_lifecycle_event=build_job_lifecycle_event(),
        message_key=str(uuid4()),
    )
    session_factory = MagicMock()
    kafka_consumer = MagicMock()

    try:
        process_job_event_message(
            message=kafka_message,
            consumer=kafka_consumer,
            session_factory=session_factory,
        )
    except ValueError as message_error:
        assert str(message_error) == "Kafka job event key does not match its job ID"
    else:
        raise AssertionError("Expected the consumer to reject a mismatched key")

    session_factory.assert_not_called()
    kafka_consumer.commit.assert_not_called()