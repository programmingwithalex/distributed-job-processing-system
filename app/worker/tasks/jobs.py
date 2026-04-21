import time
from uuid import UUID

from app.common.models.job import JobStatus
from app.common.database import database_session_factory
from app.common.services.jobs import (
    mark_job_record_completed,
    mark_job_record_processing,
    mark_job_record_queued_for_retry_or_failed,
)
from app.worker.celery_app import celery_app


TRANSIENT_FAILURE_INPUT_PREFIX = "fail-once:"
PERSISTENT_FAILURE_INPUT_PREFIX = "always-fail:"


def build_processed_result(input_value: str, attempt_count: int) -> str:
    """Build the processed result or raise a controlled failure for retry verification."""
    time.sleep(2)

    if input_value.startswith(PERSISTENT_FAILURE_INPUT_PREFIX):
        raise RuntimeError("simulated persistent job processing failure")

    if input_value.startswith(TRANSIENT_FAILURE_INPUT_PREFIX) and attempt_count == 1:
        raise RuntimeError("simulated transient job processing failure")

    return f"processed:{input_value}"


@celery_app.task(name="app.worker.tasks.jobs.process_submitted_job")
def process_submitted_job(job_id: str) -> None:
    """Process a submitted job by updating its persisted lifecycle state."""
    database_session = database_session_factory()
    parsed_job_id = UUID(job_id)
    try:
        job_record = mark_job_record_processing(
            database_session=database_session,
            job_id=parsed_job_id,
        )
        if job_record is None:
            return

        processed_result = build_processed_result(
            input_value=job_record.input_value,
            attempt_count=job_record.attempt_count,
        )
        mark_job_record_completed(
            database_session=database_session,
            job_id=parsed_job_id,
            processed_result=processed_result,
        )
    except RuntimeError as processing_error:
        updated_job_record = mark_job_record_queued_for_retry_or_failed(
            database_session=database_session,
            job_id=parsed_job_id,
            failure_message=str(processing_error),
        )
        if updated_job_record is not None and updated_job_record.status == JobStatus.QUEUED:
            process_submitted_job.delay(job_id)
            return

        raise
    finally:
        database_session.close()
