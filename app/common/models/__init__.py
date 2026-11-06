"""
Import and expose the SQLAlchemy models that describe this application's PostgreSQL tables.
Loading these modules registers jobs, dispatch commands, lifecycle events, history,
and event-offset records with the shared ORM metadata used by migrations.
The exports provide a common import surface for application services without running
any broker publisher, consumer, or Celery task.
Kafka and RabbitMQ do not use this package as their own internal database schema;
these models describe application-owned records in PostgreSQL only.
"""

from app.common.models.job import JobRecord, JobStatus, JobType
from app.common.models.job_dispatch_outbox import JobDispatchOutboxRecord
from app.common.models.job_event_outbox import JobEventOutboxRecord
from app.common.models.job_event_partition_offset import JobEventPartitionOffsetRecord
from app.common.models.job_history import JobHistoryRecord

__all__ = [
    "JobDispatchOutboxRecord",
    "JobEventOutboxRecord",
    "JobEventPartitionOffsetRecord",
    "JobHistoryRecord",
    "JobRecord",
    "JobStatus",
    "JobType",
]
