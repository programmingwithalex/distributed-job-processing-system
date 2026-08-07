from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.common.models.job import JobRecord, JobStatus, JobType
from app.common.services.jobs import (
    build_post_failure_job_status,
    job_record_has_attempts_remaining,
    mark_job_record_queued_for_retry_or_dead_lettered,
)
from app.worker.tasks.jobs import build_processed_result, transform_job_input


def build_job_record_for_retry_testing(
    attempt_count: int,
    maximum_attempt_count: int,
) -> JobRecord:
    """Build an in-memory job record for retry unit tests."""
    return JobRecord(
        input_value="retry-test",
        job_type=JobType.ECHO,
        status=JobStatus.QUEUED,
        attempt_count=attempt_count,
        maximum_attempt_count=maximum_attempt_count,
    )


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