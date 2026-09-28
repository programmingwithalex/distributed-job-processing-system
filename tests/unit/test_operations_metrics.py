from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.common.services.operations import build_operations_metrics


def test_build_operations_metrics_calculates_rates_backlog_and_consumer_lag() -> None:
    """Verify the operations response aggregates event rates and Kafka offsets."""
    sampled_at = datetime(2026, 9, 26, tzinfo=UTC)
    event_counts = SimpleNamespace(
        completed_count=10,
        retry_count=2,
        processing_count=20,
        dead_lettered_count=1,
    )
    partition_offsets = [
        SimpleNamespace(latest_published_offset=8, latest_consumed_offset=5),
        SimpleNamespace(latest_published_offset=2, latest_consumed_offset=None),
    ]
    database_session = MagicMock()
    database_session.execute.side_effect = [
        SimpleNamespace(one=lambda: event_counts),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: partition_offsets)),
    ]
    database_session.scalar.return_value = 4

    operations_metrics = build_operations_metrics(
        database_session=database_session,
        sampled_at=sampled_at,
    )

    assert operations_metrics.sampled_at == sampled_at
    assert operations_metrics.window_seconds == 300
    assert operations_metrics.throughput_jobs_per_minute == 2.0
    assert operations_metrics.retry_rate_percent == 10.0
    assert operations_metrics.failure_rate_percent == 15.0
    assert operations_metrics.outbox_backlog == 4
    assert operations_metrics.kafka_consumer_lag == 6


def test_build_operations_metrics_returns_zero_rates_without_processing_attempts() -> None:
    """Verify an idle system reports finite zero rates instead of dividing by zero."""
    event_counts = SimpleNamespace(
        completed_count=0,
        retry_count=0,
        processing_count=0,
        dead_lettered_count=0,
    )
    database_session = MagicMock()
    database_session.execute.side_effect = [
        SimpleNamespace(one=lambda: event_counts),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
    ]
    database_session.scalar.return_value = 0

    operations_metrics = build_operations_metrics(database_session=database_session)

    assert operations_metrics.throughput_jobs_per_minute == 0.0
    assert operations_metrics.retry_rate_percent == 0.0
    assert operations_metrics.failure_rate_percent == 0.0