from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.models.job_event_outbox import JobEventOutboxRecord
from app.common.models.job_event_partition_offset import JobEventPartitionOffsetRecord
from app.common.models.job_history import JobHistoryRecord
from app.common.schemas.job_events import JobLifecycleEventType
from app.common.schemas.operations import OperationsMetricsResponse

OPERATIONS_METRICS_WINDOW_SECONDS = 300


def build_operations_metrics(
    database_session: Session,
    sampled_at: datetime | None = None,
) -> OperationsMetricsResponse:
    """Calculate rolling job metrics and current Kafka delivery backlog.

    Retry rate is retry-scheduled events divided by processing attempts. Failure
    rate includes both retry-scheduled and dead-lettered events over those attempts.

    Args:
        database_session: Session used to read operational data
        sampled_at: Optional timestamp for deterministic metric tests

    Returns:
        Operations metrics calculated from projected events and outbox offsets
    """
    current_time = sampled_at or datetime.now(UTC)
    window_start = current_time - timedelta(seconds=OPERATIONS_METRICS_WINDOW_SECONDS)
    event_counts = database_session.execute(
        select(
            func.count()
            .filter(JobHistoryRecord.event_type == JobLifecycleEventType.COMPLETED.value)
            .label("completed_count"),
            func.count()
            .filter(JobHistoryRecord.event_type == JobLifecycleEventType.RETRY_SCHEDULED.value)
            .label("retry_count"),
            func.count()
            .filter(JobHistoryRecord.event_type == JobLifecycleEventType.PROCESSING.value)
            .label("processing_count"),
            func.count()
            .filter(JobHistoryRecord.event_type == JobLifecycleEventType.DEAD_LETTERED.value)
            .label("dead_lettered_count"),
        ).where(JobHistoryRecord.occurred_at >= window_start)
    ).one()
    completed_count = event_counts.completed_count
    retry_count = event_counts.retry_count
    processing_count = event_counts.processing_count
    dead_lettered_count = event_counts.dead_lettered_count

    outbox_backlog = database_session.scalar(
        select(func.count())
        .select_from(JobEventOutboxRecord)
        .where(JobEventOutboxRecord.published_at.is_(None))
    ) or 0
    partition_offsets = database_session.execute(
        select(JobEventPartitionOffsetRecord)
    ).scalars().all()
    kafka_consumer_lag = 0
    for partition_offset in partition_offsets:
        published_offset = partition_offset.latest_published_offset
        if published_offset is None:
            continue
        consumed_offset = partition_offset.latest_consumed_offset
        kafka_consumer_lag += (
            published_offset + 1
            if consumed_offset is None
            else max(published_offset - consumed_offset, 0)
        )

    attempt_denominator = max(processing_count, 1)
    return OperationsMetricsResponse(
        sampled_at=current_time,
        window_seconds=OPERATIONS_METRICS_WINDOW_SECONDS,
        throughput_jobs_per_minute=completed_count / (OPERATIONS_METRICS_WINDOW_SECONDS / 60),
        retry_rate_percent=retry_count / attempt_denominator * 100,
        failure_rate_percent=(retry_count + dead_lettered_count) / attempt_denominator * 100,
        outbox_backlog=outbox_backlog,
        kafka_consumer_lag=kafka_consumer_lag,
    )