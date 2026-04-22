from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.common.database import get_database_session
from app.common.models.job import JobStatus
from app.common.schemas.job import JobCreateRequest, JobStatusResponse
from app.common.services.jobs import create_job_record, get_job_record_by_id, list_job_records
from app.worker.tasks.jobs import process_submitted_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_job(
    job_create_request: JobCreateRequest,
    database_session: Session = Depends(get_database_session),
) -> JobStatusResponse:
    """Create a queued job record and dispatch it to the Celery worker."""
    job_record = create_job_record(
        database_session=database_session,
        input_value=job_create_request.input_value,
    )
    process_submitted_job.delay(str(job_record.id))
    return JobStatusResponse.model_validate(job_record)


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status_by_id(
    job_id: UUID,
    database_session: Session = Depends(get_database_session),
) -> JobStatusResponse:
    """Return the current persisted status for a previously submitted job."""
    job_record = get_job_record_by_id(database_session=database_session, job_id=job_id)
    if job_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    return JobStatusResponse.model_validate(job_record)


@router.get("", response_model=list[JobStatusResponse])
def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    database_session: Session = Depends(get_database_session),
) -> list[JobStatusResponse]:
    """List persisted jobs with optional status filtering and pagination."""
    job_records = list_job_records(
        database_session=database_session,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return [JobStatusResponse.model_validate(job_record) for job_record in job_records]
