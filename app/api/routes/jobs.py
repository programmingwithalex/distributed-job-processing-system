from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.common.database import get_database_session
from app.common.schemas.job import JobCreateRequest, JobStatusResponse
from app.common.services.jobs import create_job_record, get_job_record_by_id
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
