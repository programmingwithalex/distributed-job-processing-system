"""
Create the Celery application used both to publish execution commands and to run workers.
Configure RabbitMQ as the broker, JSON message serialization, persistent delivery,
and publisher confirmations so the dispatcher can distinguish accepted sends from failures.
Enable late task acknowledgement and worker-loss redelivery so interrupted work can
return to the queue, while application locks and terminal-state checks handle duplicates.
This configuration does not itself execute a job or store its result; task definitions
provide execution behavior and PostgreSQL remains the system of record.
"""

from celery import Celery

from app.common.config import get_application_settings
from app.common.logging import configure_application_logging

application_settings = get_application_settings()
configure_application_logging()

celery_app = Celery(
    "job_worker",
    broker=application_settings.celery_broker_url,
    include=["app.worker.tasks.jobs"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_default_delivery_mode="persistent",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"confirm_publish": True},
    broker_connection_timeout=5,
    timezone="UTC",
)
