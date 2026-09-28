from fastapi import APIRouter, Depends
from prometheus_client import Gauge
from sqlalchemy.orm import Session

from app.common.database import get_database_session
from app.common.schemas.operations import OperationsMetricsResponse
from app.common.services.operations import build_operations_metrics

router = APIRouter(prefix="/operations", tags=["operations"])
JOB_COMPLETION_THROUGHPUT_PER_MINUTE = Gauge(
    "job_completion_throughput_per_minute",
    "Completed jobs per minute over the rolling operations window",
)
JOB_RETRY_RATE_PERCENT = Gauge(
    "job_retry_rate_percent",
    "Retry-scheduled lifecycle events as a percentage of processing attempts",
)
JOB_FAILURE_RATE_PERCENT = Gauge(
    "job_failure_rate_percent",
    "Dead-lettered lifecycle events as a percentage of processing attempts",
)
JOB_EVENT_OUTBOX_BACKLOG = Gauge(
    "job_event_outbox_backlog",
    "Number of committed job lifecycle events not yet acknowledged by Kafka",
)
JOB_EVENT_CONSUMER_LAG = Gauge(
    "job_event_consumer_lag",
    "Kafka event offsets published but not yet projected to PostgreSQL history",
)


@router.get("/metrics", response_model=OperationsMetricsResponse)
def get_operations_metrics(
    database_session: Session = Depends(get_database_session),
) -> OperationsMetricsResponse:
    """Return operations metrics and publish their latest values to Prometheus.

    Args:
        database_session: Request-scoped SQLAlchemy session

    Returns:
        Rolling throughput, retry, failure, outbox, and consumer-lag metrics
    """
    operations_metrics = build_operations_metrics(database_session=database_session)
    JOB_COMPLETION_THROUGHPUT_PER_MINUTE.set(
        operations_metrics.throughput_jobs_per_minute
    )
    JOB_RETRY_RATE_PERCENT.set(operations_metrics.retry_rate_percent)
    JOB_FAILURE_RATE_PERCENT.set(operations_metrics.failure_rate_percent)
    JOB_EVENT_OUTBOX_BACKLOG.set(operations_metrics.outbox_backlog)
    JOB_EVENT_CONSUMER_LAG.set(operations_metrics.kafka_consumer_lag)
    return operations_metrics