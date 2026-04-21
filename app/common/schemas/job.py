from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.common.models.job import JobStatus


class JobCreateRequest(BaseModel):
    """Define the API request body for submitting a new job."""

    input_value: str = Field(min_length=1, max_length=255)


class JobStatusResponse(BaseModel):
    """Define the API response body for returning job metadata and status."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    input_value: str
    status: JobStatus
    result: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
