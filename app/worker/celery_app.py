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
    timezone="UTC",
)
