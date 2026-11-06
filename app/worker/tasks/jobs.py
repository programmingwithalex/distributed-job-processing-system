"""
Define the Celery task that receives job IDs from RabbitMQ and performs the actual work.
Load the job from PostgreSQL, acquire its execution lock, and skip redeliveries of
jobs that already completed or reached a terminal failure state.
Record execution attempts, results, processing errors, and lifecycle events through
the job services rather than storing them in the broker-delivery outbox.
Business retries are scheduled through the transactional dispatch outbox, while
worker-loss redelivery remains bounded by the job's persisted processing retry budget.
"""

import logging
import time
from uuid import UUID

from celery import Task
from celery.exceptions import Reject
from sqlalchemy.exc import OperationalError as DatabaseOperationalError
from sqlalchemy.orm import Session

from app.common.database import database_session_factory
from app.common.logging import correlation_identifier_context_scope
from app.common.models.job import JobStatus, JobType
from app.common.services.job_execution import job_execution_lock
from app.common.services.jobs import (
    calculate_job_retry_delay_seconds as calculate_job_retry_delay_seconds,
    get_job_record_by_id,
    mark_job_record_completed,
    mark_job_record_processing,
    mark_job_record_queued_for_retry_or_dead_lettered,
)
from app.worker.celery_app import celery_app

TRANSIENT_FAILURE_INPUT_PREFIX = "fail-once:"
PERSISTENT_FAILURE_INPUT_PREFIX = "always-fail:"
logger = logging.getLogger(__name__)


def transform_job_input(input_value: str, job_type: JobType) -> str:
    """
    Transform the submitted input according to the requested job type.

    Args:
        input_value: Submitted value to transform
        job_type: Processing behavior to apply

    Returns:
        Transformed input value
    """
    if job_type == JobType.ECHO:
        return input_value

    if job_type == JobType.REVERSE:
        return input_value[::-1]

    if job_type == JobType.UPPERCASE:
        return input_value.upper()

    raise RuntimeError(f"Unsupported job type: {job_type.value}")


def build_processed_result(input_value: str, job_type: JobType, attempt_count: int) -> str:
    """
    Build the processed result or raise a controlled failure for retry verification.

    Args:
        input_value: Submitted value to process
        job_type: Processing behavior to apply
        attempt_count: Current persisted processing attempt number

    Returns:
        Processed result value
    """
    # simulate worker latency and deterministic failure modes for local verification
    time.sleep(2)

    if input_value.startswith(PERSISTENT_FAILURE_INPUT_PREFIX):
        raise RuntimeError("simulated persistent job processing failure")

    if input_value.startswith(TRANSIENT_FAILURE_INPUT_PREFIX) and attempt_count == 1:
        raise RuntimeError("simulated transient job processing failure")

    transformed_input_value = transform_job_input(input_value=input_value, job_type=job_type)
    return f"processed:{transformed_input_value}"


@celery_app.task(
    bind=True,
    max_retries=None,
    name="app.worker.tasks.jobs.process_submitted_job",
)
def process_submitted_job(self: Task, job_id: str) -> None:
    """
    Serialize a job attempt and skip redelivered terminal jobs.

    The advisory lock remains held across state commits. Late acknowledgement
    permits worker-loss redelivery; PostgreSQL remains authoritative for the retry
    budget, including attempts interrupted by worker death. Business retries use
    the dispatch outbox. Binding supplies `self.retry()` for lock contention while
    preserving Celery retry metadata.

    Args:
        self: Bound Celery task instance used to schedule retries
        job_id: String representation of the persisted job identifier
    """
    database_session = database_session_factory()
    parsed_job_id = UUID(job_id)
    correlation_identifier = f"job:{job_id}"
    with correlation_identifier_context_scope(correlation_identifier=correlation_identifier):
        try:
            with job_execution_lock(parsed_job_id) as acquired:
                if not acquired:
                    raise self.retry(countdown=2)
                current_job = get_job_record_by_id(database_session, parsed_job_id)
                if current_job is None or current_job.status in (
                    JobStatus.COMPLETED,
                    JobStatus.DEAD_LETTERED,
                    JobStatus.FAILED,
                ):
                    logger.info("Skipped missing or terminal job %s", job_id)
                    return
                if current_job.attempt_count >= current_job.maximum_attempt_count:
                    mark_job_record_queued_for_retry_or_dead_lettered(
                        database_session,
                        parsed_job_id,
                        failure_message="Retry budget exhausted after an interrupted attempt",
                    )
                    return
                execute_job_attempt(database_session, parsed_job_id)
        except DatabaseOperationalError as database_error:
            database_session.rollback()
            logger.warning("Database unavailable during job %s: %s", job_id, database_error)
            time.sleep(1)
            raise Reject("database unavailable", requeue=True) from database_error
        finally:
            database_session.close()


def execute_job_attempt(database_session: Session, job_id: UUID) -> None:
    """
    Run one attempt while the caller holds the job's execution lock.

    Args:
        database_session: Session used for independently committed state transitions
        job_id: Job being processed under the advisory lock
    """
    try:
        job_record = mark_job_record_processing(database_session=database_session, job_id=job_id)
        if job_record is None:
            return
        logger.info(
            "Processing job %s type %s attempt %s of %s",
            job_record.id,
            job_record.job_type.value,
            job_record.attempt_count,
            job_record.maximum_attempt_count,
        )
        processed_result = build_processed_result(
            input_value=job_record.input_value,
            job_type=job_record.job_type,
            attempt_count=job_record.attempt_count,
        )
        mark_job_record_completed(
            database_session=database_session, job_id=job_id, processed_result=processed_result
        )
        logger.info("Completed job %s", job_id)
    except RuntimeError as processing_error:
        updated_job_record = mark_job_record_queued_for_retry_or_dead_lettered(
            database_session=database_session, job_id=job_id, failure_message=str(processing_error)
        )
        if updated_job_record is not None and updated_job_record.status == JobStatus.QUEUED:
            logger.info("Durably scheduled retry for job %s", job_id)
            return
        logger.error("Job %s failed permanently", job_id)
        raise
