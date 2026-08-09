import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.common.database import get_database_session
from app.common.models.job import JobStatus
from app.common.schemas.job import JobCreateRequest, JobStatusResponse
from app.common.services.jobs import (
    create_job_record,
    create_replayed_job_record,
    get_job_record_by_id,
    list_job_records,
)
from app.worker.tasks.jobs import process_submitted_job

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


@router.post("", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_job(
    job_create_request: JobCreateRequest,
    database_session: Session = Depends(get_database_session),
) -> JobStatusResponse:
    """
    Create a queued job record and dispatch it to the Celery worker.

    Args:
        job_create_request: Validated job submission payload
        database_session: Request-scoped SQLAlchemy session

    Returns:
        Persisted queued job metadata
    """
    job_record = create_job_record(
        database_session=database_session,
        input_value=job_create_request.input_value,
        job_type=job_create_request.job_type,
        maximum_attempt_count=job_create_request.maximum_attempt_count,
    )
    process_submitted_job.delay(str(job_record.id))
    logger.info(
        "Submitted job %s with type %s and input %s",
        job_record.id,
        job_record.job_type.value,
        job_record.input_value,
    )
    return JobStatusResponse.model_validate(job_record)


@router.post(
    "/{job_id}/replay",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def replay_dead_lettered_job(
    job_id: UUID,
    database_session: Session = Depends(get_database_session),
) -> JobStatusResponse:
    """
    Create and dispatch a new job from a dead-lettered source job.

    The source remains unchanged as failure history while the new queued job records
    its lineage through `replayed_from_job_id`.

    Args:
        job_id: Identifier of the dead-lettered source job
        database_session: Request-scoped SQLAlchemy session

    Returns:
        Persisted queued replay job metadata
    """
    source_job_record = get_job_record_by_id(
        database_session=database_session,
        job_id=job_id,
    )
    if source_job_record is None:
        logger.warning("Job %s was not found during replay", job_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        replayed_job_record = create_replayed_job_record(
            database_session=database_session,
            dead_lettered_job_record=source_job_record,
        )
    except ValueError as replay_error:
        logger.warning("Job %s cannot be replayed because it is not dead-lettered", job_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(replay_error),
        ) from replay_error

    # dispatch only after the replay row and its lineage are committed
    process_submitted_job.delay(str(replayed_job_record.id))
    logger.info("Replayed dead-lettered job %s as job %s", job_id, replayed_job_record.id)
    return JobStatusResponse.model_validate(replayed_job_record)


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status_by_id(
    job_id: UUID,
    database_session: Session = Depends(get_database_session),
) -> JobStatusResponse:
    """
    Return the current persisted status for a previously submitted job.

    Args:
        job_id: Identifier of the job to retrieve
        database_session: Request-scoped SQLAlchemy session

    Returns:
        Current persisted job metadata
    """
    job_record = get_job_record_by_id(database_session=database_session, job_id=job_id)
    if job_record is None:
        logger.warning("Job %s was not found during status lookup", job_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    logger.info("Fetched job %s with status %s", job_record.id, job_record.status.value)
    return JobStatusResponse.model_validate(job_record)


@router.get("", response_model=list[JobStatusResponse])
def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    database_session: Session = Depends(get_database_session),
) -> list[JobStatusResponse]:
    """
    List persisted jobs with optional status filtering and pagination.

    Args:
        status_filter: Optional status used to filter jobs
        limit: Maximum number of jobs to return
        offset: Number of jobs to skip
        database_session: Request-scoped SQLAlchemy session

    Returns:
        Ordered job metadata matching the requested filters
    """
    job_records = list_job_records(
        database_session=database_session,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    logger.info(
        "Listed %s jobs with status_filter=%s limit=%s offset=%s",
        len(job_records),
        status_filter.value if status_filter is not None else "all",
        limit,
        offset,
    )
    return [JobStatusResponse.model_validate(job_record) for job_record in job_records]
