import enum
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.common.models.job import JobStatus, JobType


class JobLifecycleEventType(str, enum.Enum):
    """Enumerate the version-one job lifecycle event names."""

    SUBMITTED = "submitted"
    PROCESSING = "processing"
    RETRY_SCHEDULED = "retry_scheduled"
    COMPLETED = "completed"
    DEAD_LETTERED = "dead_lettered"
    REPLAYED = "replayed"


class JobLifecycleEvent(BaseModel):
    """Describe a versioned job lifecycle event shared by producers and consumers."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: JobLifecycleEventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    job_id: uuid.UUID
    sequence_number: int = Field(ge=1)
    job_type: JobType
    status: JobStatus
    attempt_count: int = Field(ge=0)
    maximum_attempt_count: int = Field(ge=1)
    error_message: str | None = None
    replayed_from_job_id: uuid.UUID | None = None