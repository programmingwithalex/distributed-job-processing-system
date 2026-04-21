import time
from uuid import UUID

from app.common.database import database_session_factory
from app.common.services.jobs import (
    mark_job_record_completed,
    mark_job_record_failed,
    mark_job_record_processing,
)
from app.worker.celery_app import celery_app


@celery_app.task(name="app.worker.tasks.jobs.process_submitted_job")
def process_submitted_job(job_id: str) -> None:
    """Process a submitted job by updating its persisted lifecycle state."""
    database_session = database_session_factory()
    try:
        parsed_job_id = UUID(job_id)
        job_record = mark_job_record_processing(
            database_session=database_session,
            job_id=parsed_job_id,
        )
        if job_record is None:
            return

        time.sleep(2)
        processed_result = f"processed:{job_record.input_value}"
        mark_job_record_completed(
            database_session=database_session,
            job_id=parsed_job_id,
            processed_result=processed_result,
        )
    except Exception as exc:
        mark_job_record_failed(
            database_session=database_session,
            job_id=UUID(job_id),
            failure_message=str(exc),
        )
        raise
    finally:
        database_session.close()
