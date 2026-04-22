from app.common.models.job import JobType
from app.common.schemas.job import JobCreateRequest
from app.worker.tasks.jobs import transform_job_input


def test_job_create_request_defaults_to_echo_job_type() -> None:
    """Verify job creation defaults to the echo job type when none is supplied."""
    job_create_request = JobCreateRequest.model_validate({"input_value": "hello-world"})

    assert job_create_request.job_type == JobType.ECHO


def test_transform_job_input_supports_each_job_type() -> None:
    """Verify job input transformation matches the requested job type."""
    assert transform_job_input(input_value="hello-world", job_type=JobType.ECHO) == "hello-world"
    assert transform_job_input(input_value="hello-world", job_type=JobType.REVERSE) == "dlrow-olleh"
    assert transform_job_input(input_value="hello-world", job_type=JobType.UPPERCASE) == "HELLO-WORLD"