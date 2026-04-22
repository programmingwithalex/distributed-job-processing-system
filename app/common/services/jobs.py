from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.common.config import get_application_settings
from app.common.models.job import JobRecord, JobStatus


application_settings = get_application_settings()


def resolve_job_maximum_attempt_count(maximum_attempt_count: int | None) -> int:
    """Resolve the effective retry budget for a newly created job.

    Args:
        maximum_attempt_count: Optional per-job retry limit override

    Returns:
        Effective retry budget for the new job record
    """
    if maximum_attempt_count is not None:
        return maximum_attempt_count

    return application_settings.default_maximum_attempt_count


def create_job_record(
    database_session: Session,
    input_value: str,
    maximum_attempt_count: int | None = None,
) -> JobRecord:
    """Persist a new queued job record and return the stored row."""
    job_record = JobRecord(
        input_value=input_value,
        status=JobStatus.QUEUED,
        attempt_count=0,
        maximum_attempt_count=resolve_job_maximum_attempt_count(maximum_attempt_count=maximum_attempt_count),
    )
    database_session.add(job_record)
    database_session.commit()
    database_session.refresh(job_record)
    return job_record


def get_job_record_by_id(database_session: Session, job_id: UUID) -> JobRecord | None:
    """Fetch a job record by its identifier from Postgres."""
    job_lookup_statement = select(JobRecord).where(JobRecord.id == job_id)
    return database_session.execute(job_lookup_statement).scalar_one_or_none()


def build_job_record_listing_statement(
    status_filter: JobStatus | None,
    limit: int,
    offset: int,
) -> Select[tuple[JobRecord]]:
    """Build the query used to list persisted job records.

    Args:
        status_filter: Optional job status used to narrow the result set
        limit: Maximum number of job records to return
        offset: Number of rows to skip before returning records

    Returns:
        SQLAlchemy select statement for listing jobs newest first
    """
    job_record_listing_statement = select(JobRecord).order_by(
        JobRecord.created_at.desc(),
        JobRecord.id.desc(),
    )

    if status_filter is not None:
        job_record_listing_statement = job_record_listing_statement.where(JobRecord.status == status_filter)

    return job_record_listing_statement.limit(limit).offset(offset)


def list_job_records(
    database_session: Session,
    status_filter: JobStatus | None,
    limit: int,
    offset: int,
) -> list[JobRecord]:
    """List persisted job records with optional filtering and pagination.

    Args:
        database_session: SQLAlchemy session used for persistence work
        status_filter: Optional job status used to narrow the result set
        limit: Maximum number of job records to return
        offset: Number of rows to skip before returning records

    Returns:
        Ordered list of matching job records
    """
    job_record_listing_statement = build_job_record_listing_statement(
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return list(database_session.execute(job_record_listing_statement).scalars().all())


def mark_job_record_processing(database_session: Session, job_id: UUID) -> JobRecord | None:
    """Mark a queued job record as actively processing."""
    job_record = get_job_record_by_id(database_session=database_session, job_id=job_id)
    if job_record is None:
        return None

    job_record.status = JobStatus.PROCESSING
    job_record.attempt_count += 1
    job_record.error_message = None
    database_session.commit()
    database_session.refresh(job_record)
    return job_record


def job_record_has_attempts_remaining(job_record: JobRecord) -> bool:
    """Return whether the job can be retried after the current failed attempt."""
    return job_record.attempt_count < job_record.maximum_attempt_count


def build_post_failure_job_status(job_record: JobRecord) -> JobStatus:
    """Return the next persisted status after a processing failure."""
    if job_record_has_attempts_remaining(job_record=job_record):
        return JobStatus.QUEUED

    return JobStatus.FAILED


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


def mark_job_record_queued_for_retry_or_failed(
    database_session: Session,
    job_id: UUID,
    failure_message: str,
) -> JobRecord | None:
    """Persist a failed attempt and either requeue the job or fail it terminally."""
    job_record = get_job_record_by_id(database_session=database_session, job_id=job_id)
    if job_record is None:
        return None

    job_record.status = build_post_failure_job_status(job_record=job_record)
    job_record.result = None
    job_record.error_message = failure_message
    database_session.commit()
    database_session.refresh(job_record)
    return job_record
