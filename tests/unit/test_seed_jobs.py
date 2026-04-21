from datetime import UTC, datetime

from app.common.models.job import JobStatus
from app.common.seed_jobs import build_seed_job_definitions


def test_build_seed_job_definitions_returns_stable_dataset() -> None:
    """Verify the deterministic seed dataset remains stable over time."""
    seeded_job_definitions = build_seed_job_definitions()

    assert [seeded_job_definition.input_value for seeded_job_definition in seeded_job_definitions] == [
        "portfolio-import",
        "position-reconciliation",
        "nav-calculation",
        "report-publication",
    ]
    assert [seeded_job_definition.status for seeded_job_definition in seeded_job_definitions] == [
        JobStatus.QUEUED,
        JobStatus.PROCESSING,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    ]
    assert [seeded_job_definition.attempt_count for seeded_job_definition in seeded_job_definitions] == [
        0,
        1,
        1,
        3,
    ]
    assert [seeded_job_definition.maximum_attempt_count for seeded_job_definition in seeded_job_definitions] == [
        3,
        3,
        3,
        3,
    ]
    assert [str(seeded_job_definition.id) for seeded_job_definition in seeded_job_definitions] == [
        "5769240a-b71f-5d22-b672-eb1ae8b330a2",
        "e1d33224-4954-5dc0-ac23-15a7dcd0e7dc",
        "e9813c0d-69a8-5866-abeb-486b7d88a5c2",
        "9952b866-682f-5316-856e-847b6735c7b8",
    ]
    assert [seeded_job_definition.created_at for seeded_job_definition in seeded_job_definitions] == [
        datetime(2026, 4, 20, 12, 0, tzinfo=UTC),
        datetime(2026, 4, 20, 12, 5, tzinfo=UTC),
        datetime(2026, 4, 20, 12, 14, tzinfo=UTC),
        datetime(2026, 4, 20, 12, 21, tzinfo=UTC),
    ]