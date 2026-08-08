from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.common.models.job import JobStatus, JobType


class JobCreateRequest(BaseModel):
    """Define the API request body for submitting a new job."""

    input_value: str = Field(min_length=1, max_length=255)
    job_type: JobType = JobType.ECHO
    maximum_attempt_count: int | None = Field(default=None, ge=1, le=10)


class JobStatusResponse(BaseModel):
    """Define the API response body for returning job metadata and status."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    input_value: str
    job_type: JobType
    status: JobStatus
    attempt_count: int
    maximum_attempt_count: int
    result: str | None
    error_message: str | None
    dead_lettered_at: datetime | None
    created_at: datetime
    updated_at: datetime
