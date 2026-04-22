from sqlalchemy.dialects import postgresql

from app.common.models.job import JobStatus
from app.common.services.jobs import build_job_record_listing_statement


def test_build_job_record_listing_statement_applies_status_filter_pagination_and_sorting() -> None:
    """Verify the job listing query includes filtering, ordering, limit, and offset."""
    job_record_listing_statement = build_job_record_listing_statement(
        status_filter=JobStatus.FAILED,
        limit=10,
        offset=20,
    )

    compiled_query_text = str(
        job_record_listing_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "WHERE jobs.status = 'failed'" in compiled_query_text
    assert "ORDER BY jobs.created_at DESC, jobs.id DESC" in compiled_query_text
    assert " LIMIT 10" in compiled_query_text
    assert " OFFSET 20" in compiled_query_text


def test_build_job_record_listing_statement_omits_status_filter_when_not_requested() -> None:
    """Verify the job listing query does not add a status predicate without a filter."""
    job_record_listing_statement = build_job_record_listing_statement(
        status_filter=None,
        limit=5,
        offset=0,
    )

    compiled_query_text = str(
        job_record_listing_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "WHERE jobs.status" not in compiled_query_text
    assert " LIMIT 5" in compiled_query_text
    assert " OFFSET 0" in compiled_query_text