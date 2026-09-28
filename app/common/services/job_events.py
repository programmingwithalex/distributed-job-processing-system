from sqlalchemy.orm import Session

from app.common.config import get_application_settings
from app.common.models.job import JobRecord
from app.common.models.job_event_outbox import JobEventOutboxRecord
from app.common.schemas.job_events import JobLifecycleEvent, JobLifecycleEventType

application_settings = get_application_settings()


def add_job_lifecycle_event_to_outbox(
    database_session: Session,
    job_record: JobRecord,
    event_type: JobLifecycleEventType,
) -> JobLifecycleEvent:
    """Add a typed lifecycle event to the current database transaction.

    Args:
        database_session: Session owning the job-state transaction
        job_record: Job state represented by the event
        event_type: Lifecycle transition being recorded

    Returns:
        Typed event added to the outbox
    """
    job_record.lifecycle_event_sequence = (job_record.lifecycle_event_sequence or 0) + 1
    job_lifecycle_event = JobLifecycleEvent(
        event_type=event_type,
        job_id=job_record.id,
        sequence_number=job_record.lifecycle_event_sequence,
        job_type=job_record.job_type,
        status=job_record.status,
        attempt_count=job_record.attempt_count,
        maximum_attempt_count=job_record.maximum_attempt_count,
        error_message=job_record.error_message,
        replayed_from_job_id=job_record.replayed_from_job_id,
    )
    database_session.add(
        JobEventOutboxRecord(
            event_id=job_lifecycle_event.event_id,
            job_id=job_record.id,
            sequence_number=job_lifecycle_event.sequence_number,
            topic=application_settings.job_events_topic,
            message_key=str(job_record.id),
            event_type=job_lifecycle_event.event_type.value,
            payload=job_lifecycle_event.model_dump(mode="json"),
        )
    )
    return job_lifecycle_event