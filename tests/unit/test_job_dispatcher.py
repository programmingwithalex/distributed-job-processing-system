"""
Test how the dispatcher updates PostgreSQL delivery records when publishing to RabbitMQ.
Mock the database session and Celery publishing API to check confirmations, stable
task IDs, delivery errors, and retry timing without requiring a running broker.
These tests exercise command delivery rather than job execution or Kafka history,
so worker retry budgets and processing results are tested in separate modules.
They validate dispatcher decisions but do not replace live broker-outage or
database-transaction recovery checks.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from kombu.exceptions import OperationalError

from app.common.models.job_dispatch_outbox import JobDispatchOutboxRecord
from app.worker.job_dispatcher import dispatch_pending_jobs


def test_dispatch_marks_broker_confirmed_command_delivered() -> None:
    """Record confirmed delivery with a stable task ID and one transaction commit."""
    current_time = datetime(2026, 11, 4, tzinfo=UTC)
    record = JobDispatchOutboxRecord(job_id=uuid4(), attempt_count=0)
    database_session = MagicMock()
    database_session.execute.return_value.scalars.return_value.all.return_value = [record]
    with patch("app.worker.job_dispatcher.process_submitted_job.apply_async") as publish:
        assert dispatch_pending_jobs(database_session, current_time=current_time) == 1
    publish.assert_called_once_with(
        args=[str(record.job_id)], task_id=str(record.job_id), retry=False
    )
    assert record.dispatched_at == current_time
    assert record.attempt_count == 1
    assert record.last_error is None
    database_session.commit.assert_called_once()


def test_dispatch_broker_failure_preserves_pending_command_for_retry() -> None:
    """Keep failed delivery pending with exponential backoff rather than losing it."""
    current_time = datetime(2026, 11, 4, tzinfo=UTC)
    record = JobDispatchOutboxRecord(job_id=uuid4(), attempt_count=2)
    database_session = MagicMock()
    database_session.execute.return_value.scalars.return_value.all.return_value = [record]
    with patch(
        "app.worker.job_dispatcher.process_submitted_job.apply_async",
        side_effect=OperationalError("broker unavailable"),
    ):
        assert dispatch_pending_jobs(database_session, current_time=current_time) == 0
    assert record.dispatched_at is None
    assert record.next_attempt_at == current_time + timedelta(seconds=4)
    assert record.last_error == "broker unavailable"
    database_session.commit.assert_called_once()
