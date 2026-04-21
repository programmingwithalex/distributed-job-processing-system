from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.models.job import JobRecord, JobStatus


def create_job_record(database_session: Session, input_value: str) -> JobRecord:
    """Persist a new queued job record and return the stored row."""
    job_record = JobRecord(input_value=input_value, status=JobStatus.QUEUED)
    database_session.add(job_record)
    database_session.commit()
    database_session.refresh(job_record)
    return job_record


def get_job_record_by_id(database_session: Session, job_id: UUID) -> JobRecord | None:
    """Fetch a job record by its identifier from Postgres."""
    job_lookup_statement = select(JobRecord).where(JobRecord.id == job_id)
    return database_session.execute(job_lookup_statement).scalar_one_or_none()


def mark_job_record_processing(database_session: Session, job_id: UUID) -> JobRecord | None:
    """Mark a queued job record as actively processing."""
    job_record = get_job_record_by_id(database_session=database_session, job_id=job_id)
    if job_record is None:
        return None

    job_record.status = JobStatus.PROCESSING
    job_record.error_message = None
    database_session.commit()
    database_session.refresh(job_record)
    return job_record


def mark_job_record_completed(
    database_session: Session,
    job_id: UUID,
    processed_result: str,
) -> JobRecord | None:
    """Mark a job record as completed and store the processed result."""
    job_record = get_job_record_by_id(database_session=database_session, job_id=job_id)
    if job_record is None:
        return None

    job_record.status = JobStatus.COMPLETED
    job_record.result = processed_result
    job_record.error_message = None
    database_session.commit()
    database_session.refresh(job_record)
    return job_record


def mark_job_record_failed(
    database_session: Session,
    job_id: UUID,
    failure_message: str,
) -> JobRecord | None:
    """Mark a job record as failed and store the failure reason."""
    job_record = get_job_record_by_id(database_session=database_session, job_id=job_id)
    if job_record is None:
        return None

    job_record.status = JobStatus.FAILED
    job_record.error_message = failure_message
    database_session.commit()
    database_session.refresh(job_record)
    return job_record
