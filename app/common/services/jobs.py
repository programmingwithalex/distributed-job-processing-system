from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.common.config import get_application_settings
from app.common.models.job import JobRecord, JobStatus, JobType
from app.common.schemas.job_events import JobLifecycleEventType
from app.common.services.job_events import add_job_lifecycle_event_to_outbox

application_settings = get_application_settings()


def resolve_job_maximum_attempt_count(maximum_attempt_count: int | None) -> int:
    """
    Resolve the effective retry budget for a newly created job.

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
    job_type: JobType,
    maximum_attempt_count: int | None = None,
    replayed_from_job_id: UUID | None = None,
) -> JobRecord:
    """
    Persist a new queued job record and return the stored row.

    Args:
        database_session: SQLAlchemy session used for persistence work
        input_value: Input value submitted for processing
        job_type: Processing behavior requested for the job
        maximum_attempt_count: Optional per-job retry limit override
        replayed_from_job_id: Optional identifier of the dead-lettered source job

    Returns:
        Persisted queued job record
    """
    return _persist_new_job_record(
        database_session=database_session,
        input_value=input_value,
        job_type=job_type,
        maximum_attempt_count=maximum_attempt_count,
        replayed_from_job_id=replayed_from_job_id,
        event_type=JobLifecycleEventType.SUBMITTED,
    )


def _persist_new_job_record(
    database_session: Session,
    input_value: str,
    job_type: JobType,
    maximum_attempt_count: int | None,
    replayed_from_job_id: UUID | None,
    event_type: JobLifecycleEventType,
) -> JobRecord:
    """Persist a new job and its initial lifecycle event in one transaction.

    Args:
        database_session: Session used for the atomic database write
        input_value: Input value submitted for processing
        job_type: Processing behavior requested for the job
        maximum_attempt_count: Optional per-job retry limit override
        replayed_from_job_id: Optional identifier of the source job
        event_type: Initial lifecycle event to record

    Returns:
        Persisted queued job record
    """
    job_record = JobRecord(
        id=uuid4(),
        input_value=input_value,
        job_type=job_type,
        status=JobStatus.QUEUED,
        attempt_count=0,
        lifecycle_event_sequence=0,
        maximum_attempt_count=resolve_job_maximum_attempt_count(maximum_attempt_count=maximum_attempt_count),
        replayed_from_job_id=replayed_from_job_id,
    )
    database_session.add(job_record)
    add_job_lifecycle_event_to_outbox(
        database_session=database_session,
        job_record=job_record,
        event_type=event_type,
    )
    database_session.commit()
    database_session.refresh(job_record)
    return job_record


def create_replayed_job_record(
    database_session: Session,
    dead_lettered_job_record: JobRecord,
) -> JobRecord:
    """
    Create a fresh queued job linked to a dead-lettered source job.

    The replay copies the source input, processing type, and retry budget while
    preserving the source record as immutable failure history.

    Args:
        database_session: SQLAlchemy session used for persistence work
        dead_lettered_job_record: Dead-lettered job used as the replay source

    Returns:
        Persisted queued replay job linked to the source job

    Raises:
        ValueError: Raised when the source job is not dead-lettered
    """
    if dead_lettered_job_record.status != JobStatus.DEAD_LETTERED:
        raise ValueError("Only dead-lettered jobs can be replayed")

    # create a new job so the original failure remains an immutable audit record
    return _persist_new_job_record(
        database_session=database_session,
        input_value=dead_lettered_job_record.input_value,
        job_type=dead_lettered_job_record.job_type,
        maximum_attempt_count=dead_lettered_job_record.maximum_attempt_count,
        replayed_from_job_id=dead_lettered_job_record.id,
        event_type=JobLifecycleEventType.REPLAYED,
    )


def get_job_record_by_id(
    database_session: Session,
    job_id: UUID,
    *,
    lock_for_update: bool = False,
) -> JobRecord | None:
    """
    Fetch a job record by its identifier from Postgres.

    Args:
        database_session: SQLAlchemy session used for persistence work
        job_id: Identifier of the job to retrieve
        lock_for_update: Whether to lock the row until the transaction completes

    Returns:
        Matching job record, or None when the job does not exist
    """
    job_lookup_statement = select(JobRecord).where(JobRecord.id == job_id)
    if lock_for_update:
        job_lookup_statement = job_lookup_statement.with_for_update()
    return database_session.execute(job_lookup_statement).scalar_one_or_none()


def build_job_record_listing_statement(
    status_filter: JobStatus | None,
    limit: int,
    offset: int,
) -> Select[tuple[JobRecord]]:
    """
    Build the query used to list persisted job records.

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
    """
    List persisted job records with optional filtering and pagination.

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
    """
    Mark a queued job record as actively processing.

    Args:
        database_session: SQLAlchemy session used for persistence work
        job_id: Identifier of the job starting an attempt

    Returns:
        Updated job record, or None when the job does not exist
    """
    job_record = get_job_record_by_id(
        database_session=database_session,
        job_id=job_id,
        lock_for_update=True,
    )
    if job_record is None:
        return None

    job_record.status = JobStatus.PROCESSING
    job_record.attempt_count += 1
    job_record.error_message = None
    add_job_lifecycle_event_to_outbox(
        database_session=database_session,
        job_record=job_record,
        event_type=JobLifecycleEventType.PROCESSING,
    )
    database_session.commit()
    database_session.refresh(job_record)
    return job_record


def job_record_has_attempts_remaining(job_record: JobRecord) -> bool:
    """
    Return whether the job can be retried after the current failed attempt.

    Args:
        job_record: Job record containing the current retry metadata

    Returns:
        True when another processing attempt is available
    """
    return job_record.attempt_count < job_record.maximum_attempt_count


def build_post_failure_job_status(job_record: JobRecord) -> JobStatus:
    """
    Return the next persisted status after a processing failure.

    Args:
        job_record: Job record containing the current retry metadata

    Returns:
        Queued status when retries remain, otherwise dead-lettered status
    """
    if job_record_has_attempts_remaining(job_record=job_record):
        return JobStatus.QUEUED

    return JobStatus.DEAD_LETTERED


def mark_job_record_completed(
    database_session: Session,
    job_id: UUID,
    processed_result: str,
) -> JobRecord | None:
    """
    Mark a job record as completed and store the processed result.

    Args:
        database_session: SQLAlchemy session used for persistence work
        job_id: Identifier of the completed job
        processed_result: Result produced by the worker

    Returns:
        Updated job record, or None when the job does not exist
    """
    job_record = get_job_record_by_id(
        database_session=database_session,
        job_id=job_id,
        lock_for_update=True,
    )
    if job_record is None:
        return None

    job_record.status = JobStatus.COMPLETED
    job_record.result = processed_result
    job_record.error_message = None
    add_job_lifecycle_event_to_outbox(
        database_session=database_session,
        job_record=job_record,
        event_type=JobLifecycleEventType.COMPLETED,
    )
    database_session.commit()
    database_session.refresh(job_record)
    return job_record


def mark_job_record_failed(
    database_session: Session,
    job_id: UUID,
    failure_message: str,
) -> JobRecord | None:
    """
    Mark a job record as failed and store the failure reason.

    Args:
        database_session: SQLAlchemy session used for persistence work
        job_id: Identifier of the failed job
        failure_message: Description of the processing failure

    Returns:
        Updated job record, or None when the job does not exist
    """
    job_record = get_job_record_by_id(
        database_session=database_session,
        job_id=job_id,
        lock_for_update=True,
    )
    if job_record is None:
        return None

    job_record.status = JobStatus.FAILED
    job_record.error_message = failure_message
    database_session.commit()
    database_session.refresh(job_record)
    return job_record


def mark_job_record_queued_for_retry_or_dead_lettered(
    database_session: Session,
    job_id: UUID,
    failure_message: str,
) -> JobRecord | None:
    """
    Persist a failed attempt and either requeue or dead-letter the job.

    Args:
        database_session: SQLAlchemy session used for persistence work
        job_id: Identifier of the job whose attempt failed
        failure_message: Description of the processing failure

    Returns:
        Updated job record, or None when the job does not exist
    """
    job_record = get_job_record_by_id(database_session=database_session, job_id=job_id)
    if job_record is None:
        return None

    job_record.status = build_post_failure_job_status(job_record=job_record)
    job_record.result = None
    job_record.error_message = failure_message
    job_record.dead_lettered_at = (
        datetime.now(UTC) if job_record.status == JobStatus.DEAD_LETTERED else None
    )
    lifecycle_event_type = (
        JobLifecycleEventType.RETRY_SCHEDULED
        if job_record.status == JobStatus.QUEUED
        else JobLifecycleEventType.DEAD_LETTERED
    )
    add_job_lifecycle_event_to_outbox(
        database_session=database_session,
        job_record=job_record,
        event_type=lifecycle_event_type,
    )
    database_session.commit()
    database_session.refresh(job_record)
    return job_record
