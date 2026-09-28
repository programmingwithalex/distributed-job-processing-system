from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.common.models.job import JobStatus
from app.common.services.jobs import build_job_record_listing_statement, get_job_record_by_id


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


def test_get_job_record_by_id_locks_the_row_for_lifecycle_mutations() -> None:
    """Verify transition reads hold a PostgreSQL row lock through their commit."""
    database_session = MagicMock()
    database_session.execute.return_value.scalar_one_or_none.return_value = None

    get_job_record_by_id(
        database_session=database_session,
        job_id=uuid4(),
        lock_for_update=True,
    )

    compiled_query_text = str(
        database_session.execute.call_args.args[0].compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "FOR UPDATE" in compiled_query_text