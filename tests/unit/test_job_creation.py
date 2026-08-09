from uuid import uuid4

from app.common.models.job import JobRecord, JobStatus, JobType
from app.common.schemas.job import JobCreateRequest
from app.common.services.jobs import (
    create_job_record,
    create_replayed_job_record,
    resolve_job_maximum_attempt_count,
)


class FakeDatabaseSession:
    """Minimal fake session for testing job creation behavior without real I/O."""

    def __init__(self) -> None:
        """Initialize the fake session state used by the tests."""
        self.added_objects: list[object] = []
        self.commit_call_count = 0
        self.refresh_call_count = 0

    def add(self, database_object: object) -> None:
        """
        Record a newly added ORM object.

        Args:
            database_object: ORM object being added to the fake session
        """
        self.added_objects.append(database_object)

    def commit(self) -> None:
        """Record that the fake session committed."""
        self.commit_call_count += 1

    def refresh(self, database_object: object) -> None:
        """
        Record that the fake session refreshed an ORM object.

        Args:
            database_object: ORM object being refreshed by the fake session
        """
        self.refresh_call_count += 1


def test_job_create_request_accepts_custom_retry_budget() -> None:
    """Verify the request schema accepts a per-job retry override."""
    job_create_request = JobCreateRequest.model_validate(
        {"input_value": "always-fail:demo", "job_type": "reverse", "maximum_attempt_count": 5}
    )

    assert job_create_request.input_value == "always-fail:demo"
    assert job_create_request.job_type == JobType.REVERSE
    assert job_create_request.maximum_attempt_count == 5


def test_resolve_job_maximum_attempt_count_uses_global_default_when_override_is_missing() -> None:
    """Verify job creation falls back to the configured default retry budget."""
    assert resolve_job_maximum_attempt_count(maximum_attempt_count=None) == 3


def test_create_job_record_persists_custom_retry_budget() -> None:
    """Verify job creation stores the provided per-job retry override."""
    fake_database_session = FakeDatabaseSession()

    job_record = create_job_record(
        database_session=fake_database_session,
        input_value="always-fail:demo",
        job_type=JobType.UPPERCASE,
        maximum_attempt_count=5,
    )

    assert job_record.job_type == JobType.UPPERCASE
    assert job_record.maximum_attempt_count == 5
    assert job_record.attempt_count == 0
    assert fake_database_session.commit_call_count == 1
    assert fake_database_session.refresh_call_count == 1


def test_create_replayed_job_record_copies_source_job_and_records_lineage() -> None:
    """Verify replay creates a fresh queued job linked to its dead-lettered source."""
    fake_database_session = FakeDatabaseSession()
    dead_lettered_job_record = JobRecord(
        id=uuid4(),
        input_value="always-fail:demo",
        job_type=JobType.REVERSE,
        status=JobStatus.DEAD_LETTERED,
        maximum_attempt_count=5,
    )

    replayed_job_record = create_replayed_job_record(
        database_session=fake_database_session,
        dead_lettered_job_record=dead_lettered_job_record,
    )

    assert replayed_job_record.input_value == dead_lettered_job_record.input_value
    assert replayed_job_record.job_type == dead_lettered_job_record.job_type
    assert replayed_job_record.status == JobStatus.QUEUED
    assert replayed_job_record.attempt_count == 0
    assert replayed_job_record.maximum_attempt_count == 5
    assert replayed_job_record.replayed_from_job_id == dead_lettered_job_record.id


def test_create_replayed_job_record_rejects_non_dead_lettered_source() -> None:
    """Verify replay rejects a source job that has not exhausted its retry budget."""
    queued_job_record = JobRecord(
        id=uuid4(),
        input_value="demo",
        job_type=JobType.ECHO,
        status=JobStatus.QUEUED,
        maximum_attempt_count=3,
    )

    try:
        create_replayed_job_record(
            database_session=FakeDatabaseSession(),
            dead_lettered_job_record=queued_job_record,
        )
    except ValueError as replay_error:
        assert str(replay_error) == "Only dead-lettered jobs can be replayed"
    else:
        raise AssertionError("Expected replay to reject a non-dead-lettered source")