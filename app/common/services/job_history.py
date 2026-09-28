from uuid import UUID

from sqlalchemy import Select, delete, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.orm import Session

from app.common.models.job_event_partition_offset import JobEventPartitionOffsetRecord
from app.common.models.job_history import JobHistoryRecord
from app.common.schemas.job_events import JobLifecycleEvent
from app.common.services.job_event_offsets import record_job_event_partition_offset


def build_job_history_insert_statement(
    job_lifecycle_event: JobLifecycleEvent,
) -> Insert:
    """Build an idempotent PostgreSQL insert for one projected lifecycle event.

    Args:
        job_lifecycle_event: Validated Kafka event to project

    Returns:
        Insert statement that ignores duplicate event IDs
    """
    return (
        postgresql_insert(JobHistoryRecord)
        .values(
            event_id=job_lifecycle_event.event_id,
            job_id=job_lifecycle_event.job_id,
            sequence_number=job_lifecycle_event.sequence_number,
            event_type=job_lifecycle_event.event_type.value,
            occurred_at=job_lifecycle_event.occurred_at,
            payload=job_lifecycle_event.model_dump(mode="json"),
        )
        .on_conflict_do_nothing(index_elements=[JobHistoryRecord.event_id])
    )


def persist_job_history_event(
    database_session: Session,
    job_lifecycle_event: JobLifecycleEvent,
    source_topic: str,
    partition_number: int,
    kafka_offset: int,
) -> bool:
    """Insert one history event and commit it before a consumer commits its offset.

    Args:
        database_session: Session used to persist the projection
        job_lifecycle_event: Validated event received from Kafka
        source_topic: Kafka topic the event was read from
        partition_number: Kafka partition containing the event
        kafka_offset: Offset of the event in its partition

    Returns:
        True when a new event row was inserted, otherwise False for a duplicate
    """
    insert_result = database_session.execute(
        build_job_history_insert_statement(job_lifecycle_event=job_lifecycle_event)
    )
    record_job_event_partition_offset(
        database_session=database_session,
        topic=source_topic,
        partition_number=partition_number,
        offset=kafka_offset,
        offset_kind="consumed",
    )
    database_session.commit()
    return insert_result.rowcount == 1


def build_job_history_listing_statement(
    job_id: UUID,
    limit: int,
    offset: int,
) -> Select[tuple[JobHistoryRecord]]:
    """Build a paginated query for one job's ordered lifecycle history.

    Args:
        job_id: Identifier of the job whose history is requested
        limit: Maximum number of history events to return
        offset: Number of events to skip

    Returns:
        SQLAlchemy select statement ordered by per-job sequence
    """
    return (
        select(JobHistoryRecord)
        .where(JobHistoryRecord.job_id == job_id)
        .order_by(JobHistoryRecord.sequence_number)
        .limit(limit)
        .offset(offset)
    )


def list_job_history_events(
    database_session: Session,
    job_id: UUID,
    limit: int,
    offset: int,
) -> list[JobLifecycleEvent]:
    """Return typed lifecycle events from the history projection.

    Args:
        database_session: Session used to read projected events
        job_id: Identifier of the job whose history is requested
        limit: Maximum number of history events to return
        offset: Number of events to skip

    Returns:
        Events ordered by their per-job sequence number
    """
    history_statement = build_job_history_listing_statement(
        job_id=job_id,
        limit=limit,
        offset=offset,
    )
    history_records = database_session.execute(history_statement).scalars().all()
    return [
        JobLifecycleEvent.model_validate(history_record.payload)
        for history_record in history_records
    ]


def clear_job_history_projection(database_session: Session) -> None:
    """Clear the derived history projection before replaying retained Kafka events.

    Args:
        database_session: Session used to clear the projection
    """
    database_session.execute(delete(JobHistoryRecord))
    database_session.execute(
        update(JobEventPartitionOffsetRecord).values(latest_consumed_offset=None)
    )
    database_session.commit()