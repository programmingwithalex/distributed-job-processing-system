import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import ORMBase


class JobStatus(str, enum.Enum):
    """Enumerate the persisted lifecycle states for a submitted job."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


class JobType(str, enum.Enum):
    """Enumerate the supported processing behaviors for submitted jobs."""

    ECHO = "echo"
    REVERSE = "reverse"
    UPPERCASE = "uppercase"


class JobRecord(ORMBase):
    """Persist the system-of-record view of a submitted job."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    input_value: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[JobType] = mapped_column(
        Enum(
            JobType,
            name="job_type",
            values_callable=lambda job_type_enum: [job_type_member.value for job_type_member in job_type_enum],
        ),
        nullable=False,
        default=JobType.ECHO,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            values_callable=lambda job_status_enum: [job_status_member.value for job_status_member in job_status_enum],
        ),
        nullable=False,
        default=JobStatus.QUEUED,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    maximum_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replayed_from_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
