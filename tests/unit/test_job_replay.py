from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException, status

from app.api.routes.jobs import replay_dead_lettered_job
from app.common.models.job import JobRecord, JobStatus, JobType


def build_dead_lettered_job_record() -> JobRecord:
    """
    Build a dead-lettered job record for replay route tests.

    Returns:
        In-memory dead-lettered job record
    """
    current_timestamp = datetime.now(UTC)
    return JobRecord(
        id=uuid4(),
        input_value="always-fail:demo",
        job_type=JobType.ECHO,
        status=JobStatus.DEAD_LETTERED,
        attempt_count=3,
        maximum_attempt_count=3,
        dead_lettered_at=current_timestamp,
        created_at=current_timestamp,
        updated_at=current_timestamp,
    )


def test_replay_dead_lettered_job_creates_and_dispatches_linked_job() -> None:
    """Verify replay persists and dispatches a new job linked to its source."""
    database_session = MagicMock()
    source_job_record = build_dead_lettered_job_record()
    current_timestamp = datetime.now(UTC)
    replayed_job_record = JobRecord(
        id=uuid4(),
        input_value=source_job_record.input_value,
        job_type=source_job_record.job_type,
        status=JobStatus.QUEUED,
        attempt_count=0,
        maximum_attempt_count=source_job_record.maximum_attempt_count,
        replayed_from_job_id=source_job_record.id,
        created_at=current_timestamp,
        updated_at=current_timestamp,
    )

    with (
        patch("app.api.routes.jobs.get_job_record_by_id", return_value=source_job_record),
        patch(
            "app.api.routes.jobs.create_replayed_job_record",
            return_value=replayed_job_record,
        ),
        patch("app.api.routes.jobs.process_submitted_job.delay") as dispatch_mock,
    ):
        replay_response = replay_dead_lettered_job(
            job_id=source_job_record.id,
            database_session=database_session,
        )

    assert replay_response.id == replayed_job_record.id
    assert replay_response.replayed_from_job_id == source_job_record.id
    dispatch_mock.assert_called_once_with(str(replayed_job_record.id))


def test_replay_dead_lettered_job_returns_not_found_for_missing_source() -> None:
    """Verify replay returns not found when the source job does not exist."""
    missing_job_id = uuid4()

    with patch("app.api.routes.jobs.get_job_record_by_id", return_value=None):
        try:
            replay_dead_lettered_job(
                job_id=missing_job_id,
                database_session=MagicMock(),
            )
        except HTTPException as replay_error:
            assert replay_error.status_code == status.HTTP_404_NOT_FOUND
        else:
            raise AssertionError("Expected replay to reject a missing source job")


def test_replay_dead_lettered_job_returns_conflict_for_invalid_source_status() -> None:
    """Verify replay returns conflict when the source job is not dead-lettered."""
    source_job_record = build_dead_lettered_job_record()

    with (
        patch("app.api.routes.jobs.get_job_record_by_id", return_value=source_job_record),
        patch(
            "app.api.routes.jobs.create_replayed_job_record",
            side_effect=ValueError("Only dead-lettered jobs can be replayed"),
        ),
    ):
        try:
            replay_dead_lettered_job(
                job_id=source_job_record.id,
                database_session=MagicMock(),
            )
        except HTTPException as replay_error:
            assert replay_error.status_code == status.HTTP_409_CONFLICT
        else:
            raise AssertionError("Expected replay to reject a non-dead-lettered source")