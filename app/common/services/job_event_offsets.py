from typing import Literal

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.common.models.job_event_partition_offset import JobEventPartitionOffsetRecord

KafkaOffsetKind = Literal["published", "consumed"]


def record_job_event_partition_offset(
    database_session: Session,
    topic: str,
    partition_number: int,
    offset: int,
    offset_kind: KafkaOffsetKind,
) -> None:
    """Upsert a monotonic Kafka offset in the current database transaction.

    Args:
        database_session: Session sharing the related publish or consume transaction
        topic: Kafka topic name
        partition_number: Kafka partition number
        offset: Message offset acknowledged or projected
        offset_kind: Whether the offset was published or consumed
    """
    offset_field = f"latest_{offset_kind}_offset"
    partition_offset_insert = postgresql_insert(JobEventPartitionOffsetRecord).values(
        topic=topic,
        partition_number=partition_number,
        latest_published_offset=offset if offset_kind == "published" else None,
        latest_consumed_offset=offset if offset_kind == "consumed" else None,
    )
    partition_offset_column = getattr(JobEventPartitionOffsetRecord, offset_field)
    database_session.execute(
        partition_offset_insert.on_conflict_do_update(
            index_elements=[
                JobEventPartitionOffsetRecord.topic,
                JobEventPartitionOffsetRecord.partition_number,
            ],
            set_={
                offset_field: func.greatest(
                    func.coalesce(partition_offset_column, -1),
                    getattr(partition_offset_insert.excluded, offset_field),
                ),
                "updated_at": func.now(),
            },
        )
    )