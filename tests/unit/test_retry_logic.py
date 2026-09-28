from inspect import ismethod
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.common.models.job import JobRecord, JobStatus, JobType
from app.common.models.job_event_outbox import JobEventOutboxRecord
from app.common.schemas.job_events import JobLifecycleEventType
from app.common.services.jobs import (
    build_post_failure_job_status,
    job_record_has_attempts_remaining,
    mark_job_record_completed,
    mark_job_record_processing,
    mark_job_record_queued_for_retry_or_dead_lettered,
)
from app.worker.tasks.jobs import (
    build_processed_result,
    calculate_job_retry_delay_seconds,
    process_submitted_job,
    transform_job_input,
)


def build_job_record_for_retry_testing(
    attempt_count: int,
    maximum_attempt_count: int,
) -> JobRecord:
    """
    Build an in-memory job record for retry unit tests.

    Args:
        attempt_count: Current number of processing attempts
        maximum_attempt_count: Maximum number of allowed processing attempts

    Returns:
        In-memory queued job record
    """
    return JobRecord(
        id=uuid4(),
        input_value="retry-test",
        job_type=JobType.ECHO,
        status=JobStatus.QUEUED,
        attempt_count=attempt_count,
        lifecycle_event_sequence=0,
        maximum_attempt_count=maximum_attempt_count,
    )


def get_outbox_record(database_session: MagicMock) -> JobEventOutboxRecord:
    """Return the single outbox row added by a service transition.

    Args:
        database_session: Mock session used by the transition test

    Returns:
        Outbox row added to the session
    """
    outbox_records = [
        added_object
        for add_call in database_session.add.call_args_list
        if isinstance((added_object := add_call.args[0]), JobEventOutboxRecord)
    ]
    assert len(outbox_records) == 1
    return outbox_records[0]


def test_process_submitted_job_is_bound_to_celery_task_instance() -> None:
    """Verify Celery binds the registered task instance to the task implementation."""
    assert ismethod(process_submitted_job.run)
    assert callable(process_submitted_job.retry)


def test_calculate_job_retry_delay_seconds_applies_short_bounded_linear_backoff() -> None:
    """Verify retry delays increase by two seconds and stop increasing at six seconds."""
    assert calculate_job_retry_delay_seconds(attempt_count=1) == 2
    assert calculate_job_retry_delay_seconds(attempt_count=2) == 4
    assert calculate_job_retry_delay_seconds(attempt_count=3) == 6
    assert calculate_job_retry_delay_seconds(attempt_count=10) == 6


def test_process_submitted_job_uses_celery_retry_when_job_remains_queued() -> None:
    """Verify a retryable failure asks Celery to schedule the next attempt."""
    database_session = MagicMock()
    job_record = build_job_record_for_retry_testing(attempt_count=1, maximum_attempt_count=3)
    processing_error = RuntimeError("transient failure")
    celery_retry_signal = RuntimeError("celery retry requested")

    with (
        patch("app.worker.tasks.jobs.database_session_factory", return_value=database_session),
        patch("app.worker.tasks.jobs.mark_job_record_processing", return_value=job_record),
        patch("app.worker.tasks.jobs.build_processed_result", side_effect=processing_error),
        patch(
            "app.worker.tasks.jobs.mark_job_record_queued_for_retry_or_dead_lettered",
            return_value=job_record,
        ),
        patch.object(
            process_submitted_job,
            "retry",
            return_value=celery_retry_signal,
        ) as retry_mock,
    ):
        try:
            process_submitted_job.run(str(uuid4()))
        except RuntimeError as raised_error:
            assert raised_error is celery_retry_signal
        else:
            raise AssertionError("Expected the Celery retry signal")

    retry_mock.assert_called_once_with(
        exc=processing_error,
        countdown=calculate_job_retry_delay_seconds(attempt_count=job_record.attempt_count),
    )
    database_session.close.assert_called_once_with()


def test_process_submitted_job_does_not_retry_dead_lettered_job() -> None:
    """Verify an exhausted failure is re-raised without scheduling another attempt."""
    database_session = MagicMock()
    job_record = build_job_record_for_retry_testing(attempt_count=3, maximum_attempt_count=3)
    job_record.status = JobStatus.DEAD_LETTERED
    processing_error = RuntimeError("persistent failure")

    with (
        patch("app.worker.tasks.jobs.database_session_factory", return_value=database_session),
        patch("app.worker.tasks.jobs.mark_job_record_processing", return_value=job_record),
        patch("app.worker.tasks.jobs.build_processed_result", side_effect=processing_error),
        patch(
            "app.worker.tasks.jobs.mark_job_record_queued_for_retry_or_dead_lettered",
            return_value=job_record,
        ),
        patch.object(process_submitted_job, "retry") as retry_mock,
    ):
        try:
            process_submitted_job.run(str(uuid4()))
        except RuntimeError as raised_error:
            assert raised_error is processing_error
        else:
            raise AssertionError("Expected the processing failure")

    retry_mock.assert_not_called()
    database_session.close.assert_called_once_with()


def test_job_record_has_attempts_remaining_returns_true_before_retry_budget_is_exhausted() -> None:
    """Verify a job remains retryable while it has unused attempts."""
    job_record = build_job_record_for_retry_testing(attempt_count=1, maximum_attempt_count=3)

    assert job_record_has_attempts_remaining(job_record=job_record) is True


def test_build_post_failure_job_status_returns_dead_lettered_when_retry_budget_is_exhausted() -> None:
    """Verify exhausted jobs move to the dead-letter state."""
    job_record = build_job_record_for_retry_testing(attempt_count=3, maximum_attempt_count=3)

    assert build_post_failure_job_status(job_record=job_record) == JobStatus.DEAD_LETTERED


def test_retryable_failure_does_not_set_dead_lettered_timestamp() -> None:
    """Verify retryable jobs do not record a dead-letter transition time."""
    job_record = build_job_record_for_retry_testing(attempt_count=1, maximum_attempt_count=3)
    database_session = MagicMock()

    with patch("app.common.services.jobs.get_job_record_by_id", return_value=job_record):
        updated_job_record = mark_job_record_queued_for_retry_or_dead_lettered(
            database_session=database_session,
            job_id=uuid4(),
            failure_message="transient failure",
        )

    assert updated_job_record is not None
    assert updated_job_record.status == JobStatus.QUEUED
    assert updated_job_record.dead_lettered_at is None
    outbox_record = get_outbox_record(database_session=database_session)
    assert outbox_record.event_type == JobLifecycleEventType.RETRY_SCHEDULED.value
    assert outbox_record.payload["error_message"] == "transient failure"


def test_exhausted_failure_sets_dead_lettered_timestamp() -> None:
    """Verify exhausted jobs record a timezone-aware dead-letter transition time."""
    job_record = build_job_record_for_retry_testing(attempt_count=3, maximum_attempt_count=3)
    database_session = MagicMock()

    with patch("app.common.services.jobs.get_job_record_by_id", return_value=job_record):
        updated_job_record = mark_job_record_queued_for_retry_or_dead_lettered(
            database_session=database_session,
            job_id=uuid4(),
            failure_message="persistent failure",
        )

    assert updated_job_record is not None
    assert updated_job_record.status == JobStatus.DEAD_LETTERED
    assert updated_job_record.dead_lettered_at is not None
    assert updated_job_record.dead_lettered_at.tzinfo is not None
    outbox_record = get_outbox_record(database_session=database_session)
    assert outbox_record.event_type == JobLifecycleEventType.DEAD_LETTERED.value
    assert outbox_record.payload["status"] == JobStatus.DEAD_LETTERED.value


def test_mark_job_record_processing_adds_event_with_incremented_attempt_count() -> None:
    """Verify the processing event captures the attempt persisted by the transition."""
    job_record = build_job_record_for_retry_testing(attempt_count=0, maximum_attempt_count=3)
    database_session = MagicMock()

    with patch("app.common.services.jobs.get_job_record_by_id", return_value=job_record):
        updated_job_record = mark_job_record_processing(
            database_session=database_session,
            job_id=uuid4(),
        )

    assert updated_job_record is job_record
    outbox_record = get_outbox_record(database_session=database_session)
    assert outbox_record.event_type == JobLifecycleEventType.PROCESSING.value
    assert outbox_record.payload["attempt_count"] == 1
    assert outbox_record.sequence_number == 1
    database_session.commit.assert_called_once_with()


def test_mark_job_record_completed_adds_event_with_resulting_status() -> None:
    """Verify completion is added to the outbox before the state commit."""
    job_record = build_job_record_for_retry_testing(attempt_count=1, maximum_attempt_count=3)
    database_session = MagicMock()

    with patch("app.common.services.jobs.get_job_record_by_id", return_value=job_record):
        updated_job_record = mark_job_record_completed(
            database_session=database_session,
            job_id=uuid4(),
            processed_result="processed:demo",
        )

    assert updated_job_record is job_record
    outbox_record = get_outbox_record(database_session=database_session)
    assert outbox_record.event_type == JobLifecycleEventType.COMPLETED.value
    assert outbox_record.payload["status"] == JobStatus.COMPLETED.value
    database_session.commit.assert_called_once_with()


def test_build_processed_result_raises_for_transient_failure_on_first_attempt() -> None:
    """Verify the transient failure input pattern fails on the first attempt only."""
    try:
        build_processed_result(input_value="fail-once:demo", job_type=JobType.ECHO, attempt_count=1)
    except RuntimeError as processing_error:
        assert str(processing_error) == "simulated transient job processing failure"
    else:
        raise AssertionError("Expected a transient processing failure on the first attempt")


def test_build_processed_result_succeeds_after_transient_failure_retry() -> None:
    """Verify the transient failure input succeeds on a later retry attempt."""
    processed_result = build_processed_result(
        input_value="fail-once:demo",
        job_type=JobType.ECHO,
        attempt_count=2,
    )

    assert processed_result == "processed:fail-once:demo"


def test_transform_job_input_applies_requested_job_type() -> None:
    """Verify each supported job type applies its expected transformation."""
    assert transform_job_input(input_value="hello", job_type=JobType.ECHO) == "hello"
    assert transform_job_input(input_value="hello", job_type=JobType.REVERSE) == "olleh"
    assert transform_job_input(input_value="hello", job_type=JobType.UPPERCASE) == "HELLO"