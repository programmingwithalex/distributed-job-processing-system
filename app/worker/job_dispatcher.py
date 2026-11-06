"""
Run the background process that reads pending commands from PostgreSQL's dispatch outbox.
Use Celery's publishing API to send each job ID to RabbitMQ, then record confirmed
broker delivery or a delivery error and the next retry time in the outbox row.
This process does not execute jobs or monitor downstream workers, so its attempt count
measures delivery attempts rather than processing attempts.
A crash after RabbitMQ accepts a command but before the database commit can resend it,
which is why workers independently suppress duplicate execution.
"""

import logging
import time
from datetime import UTC, datetime, timedelta

from kombu.exceptions import OperationalError
from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError as DatabaseOperationalError
from sqlalchemy.orm import Session

from app.common.database import database_session_factory
from app.common.logging import configure_application_logging
from app.common.models.job_dispatch_outbox import JobDispatchOutboxRecord
from app.worker.tasks.jobs import process_submitted_job

DISPATCH_BATCH_SIZE = 10
DISPATCH_POLL_SECONDS = 1
logger = logging.getLogger(__name__)


def dispatch_pending_jobs(
    database_session: Session, *, current_time: datetime | None = None
) -> int:
    """
    Send due execution commands while holding row locks until delivery is committed.

    Broker confirmation can precede a process crash, so redelivery uses the same
    job ID and the worker must independently suppress duplicate execution.

    Args:
        database_session: Session used to lock and update delivery records
        current_time: Optional timestamp for deterministic retry tests

    Returns:
        Number of broker-confirmed commands in this batch
    """
    dispatch_time = current_time or datetime.now(UTC)
    statement = (
        select(JobDispatchOutboxRecord)
        .where(
            JobDispatchOutboxRecord.dispatched_at.is_(None),
            or_(
                JobDispatchOutboxRecord.next_attempt_at.is_(None),
                JobDispatchOutboxRecord.next_attempt_at <= dispatch_time,
            ),
        )
        .order_by(JobDispatchOutboxRecord.created_at, JobDispatchOutboxRecord.job_id)
        .limit(DISPATCH_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    records = database_session.execute(statement).scalars().all()
    dispatched_count = 0
    for record in records:
        record.attempt_count += 1
        try:
            process_submitted_job.apply_async(
                args=[str(record.job_id)], task_id=str(record.job_id), retry=False
            )
        except (OperationalError, OSError, TimeoutError) as dispatch_error:
            delay = min(2 ** min(record.attempt_count - 1, 9), 300)
            record.last_error = str(dispatch_error)[:1000]
            record.next_attempt_at = dispatch_time + timedelta(seconds=delay)
            logger.warning("Dispatch failed for job %s: %s", record.job_id, record.last_error)
            continue
        record.dispatched_at = dispatch_time
        record.next_attempt_at = None
        record.last_error = None
        dispatched_count += 1
    database_session.commit()
    return dispatched_count


def main() -> None:
    """Continuously deliver due commands and retry database outages."""
    configure_application_logging()
    while True:
        try:
            with database_session_factory() as database_session:
                dispatch_pending_jobs(database_session)
        except DatabaseOperationalError:
            logger.exception("Database unavailable to the job dispatcher")
        time.sleep(DISPATCH_POLL_SECONDS)


if __name__ == "__main__":
    main()
