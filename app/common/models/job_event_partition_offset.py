from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import ORMBase


class JobEventPartitionOffsetRecord(ORMBase):
    """Persist the latest published and projected offset for a Kafka partition."""

    __tablename__ = "job_event_partition_offsets"
    __table_args__ = (
        UniqueConstraint(
            "topic",
            "partition_number",
            name="uq_job_event_partition_offsets_topic_partition",
        ),
    )

    topic: Mapped[str] = mapped_column(String(255), primary_key=True)
    partition_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    latest_published_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_consumed_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )