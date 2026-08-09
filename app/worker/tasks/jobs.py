import logging
import time
from uuid import UUID

from celery import Task

from app.common.database import database_session_factory
from app.common.logging import correlation_identifier_context_scope
from app.common.models.job import JobStatus, JobType
from app.common.services.jobs import (
    mark_job_record_completed,
    mark_job_record_processing,
    mark_job_record_queued_for_retry_or_dead_lettered,
)
from app.worker.celery_app import celery_app

TRANSIENT_FAILURE_INPUT_PREFIX = "fail-once:"
PERSISTENT_FAILURE_INPUT_PREFIX = "always-fail:"
JOB_RETRY_DELAY_INCREMENT_SECONDS = 2
JOB_RETRY_MAXIMUM_DELAY_SECONDS = 6
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


def calculate_job_retry_delay_seconds(attempt_count: int) -> int:
    """
    Calculate a short bounded linear delay from the persisted attempt count.

    Args:
        attempt_count: Current persisted processing attempt number

    Returns:
        Retry delay in seconds capped at the configured maximum
    """
    bounded_attempt_count = max(attempt_count, 1)
    return min(
        JOB_RETRY_DELAY_INCREMENT_SECONDS * bounded_attempt_count,
        JOB_RETRY_MAXIMUM_DELAY_SECONDS,
    )


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
    Process a submitted job by updating its persisted lifecycle state.

    PostgreSQL remains authoritative for the attempt count and whether another retry
    is allowed. Celery supplies the bound task instance so retryable failures can use
    `self.retry()` with short bounded linear backoff while preserving the task identity
    and Celery retry metadata.

    Args:
        self: Bound Celery task instance used to schedule retries
        job_id: String representation of the persisted job identifier
    """
    database_session = database_session_factory()
    parsed_job_id = UUID(job_id)
    correlation_identifier = f"job:{job_id}"
    with correlation_identifier_context_scope(correlation_identifier=correlation_identifier):
        try:
            # persist the attempt before executing job logic
            job_record = mark_job_record_processing(
                database_session=database_session,
                job_id=parsed_job_id,
            )
            if job_record is None:
                logger.warning("Skipped processing because job %s was not found", job_id)
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
                database_session=database_session,
                job_id=parsed_job_id,
                processed_result=processed_result,
            )
            logger.info("Completed job %s", job_record.id)
        except RuntimeError as processing_error:
            # let the persisted retry budget choose requeue or dead-letter state
            updated_job_record = mark_job_record_queued_for_retry_or_dead_lettered(
                database_session=database_session,
                job_id=parsed_job_id,
                failure_message=str(processing_error),
            )
            if updated_job_record is not None and updated_job_record.status == JobStatus.QUEUED:
                retry_delay_seconds = calculate_job_retry_delay_seconds(
                    attempt_count=updated_job_record.attempt_count,
                )
                logger.warning(
                    "Retrying job %s in %s seconds after attempt %s of %s failed",
                    updated_job_record.id,
                    retry_delay_seconds,
                    updated_job_record.attempt_count,
                    updated_job_record.maximum_attempt_count,
                )
                # schedule short bounded backoff while preserving Celery task identity
                raise self.retry(
                    exc=processing_error,
                    countdown=retry_delay_seconds,
                )

            logger.error("Job %s failed permanently", job_id)
            raise
        finally:
            database_session.close()
