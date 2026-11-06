"""
Define the PostgreSQL table that records execution commands awaiting RabbitMQ delivery.
Each row references a job through job_id and stores delivery attempts, retry timing,
broker-delivery errors, and the timestamp when RabbitMQ confirmed receipt.
The dispatcher uses these rows to recover from failed sends without losing committed
jobs; worker execution attempts, results, and processing errors remain in jobs.
This is not a Kafka model, and confirmed delivery does not mean the job has completed.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import ORMBase


class JobDispatchOutboxRecord(ORMBase):
    """Store one recoverable execution command per submitted job."""

    __tablename__ = "job_dispatch_outbox"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
