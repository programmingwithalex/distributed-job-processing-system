"""
Provide the per-job PostgreSQL advisory lock used by Celery workers before execution.
Hold the lock on a separate connection so committing job state does not release it
and allow another worker to process the same job concurrently.
The lock is released when its transaction ends or PostgreSQL detects the connection
has closed, including after worker failure.
This module does not publish commands or track delivery; the worker must still check
terminal job status, and external side effects need their own idempotency mechanism.
"""

from collections.abc import Generator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import func, select

from app.common.database import database_engine


@contextmanager
def job_execution_lock(job_id: UUID) -> Generator[bool, None, None]:
    """
    Hold a transaction-scoped advisory lock independently of job-state commits.

    Connection closure or worker death releases the lock without leaving a lease
    to clean up. A rare 63-bit collision only serializes unrelated jobs.

    Args:
        job_id: Stable identifier used to derive the advisory lock key

    Returns:
        Context manager yielding whether this worker owns the execution lock
    """
    lock_key = job_id.int % (1 << 63)
    with database_engine.begin() as connection:
        acquired = connection.execute(select(func.pg_try_advisory_xact_lock(lock_key))).scalar_one()
        yield bool(acquired)
