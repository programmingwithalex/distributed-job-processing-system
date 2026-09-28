from datetime import datetime

from pydantic import BaseModel


class OperationsMetricsResponse(BaseModel):
    """Describe rolling job throughput, retry, failure, backlog, and lag metrics."""

    sampled_at: datetime
    window_seconds: int
    throughput_jobs_per_minute: float
    retry_rate_percent: float
    failure_rate_percent: float
    outbox_backlog: int
    kafka_consumer_lag: int