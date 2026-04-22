import argparse
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.common.database import database_session_factory
from app.common.models.job import JobRecord, JobStatus, JobType


logger = logging.getLogger(__name__)

SEED_NAMESPACE_UUID = uuid.UUID("7f3d25f3-c01d-4a59-9f5f-0f16d47fc87a")
SEED_REFERENCE_TIMESTAMP = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SeedJobDefinition:
    """Describe a deterministic job row that can be inserted into Postgres."""

    id: uuid.UUID
    input_value: str
    job_type: JobType
    status: JobStatus
    attempt_count: int
    maximum_attempt_count: int
    result: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


def build_seeded_job_identifier(job_slug: str) -> uuid.UUID:
    """Build a deterministic UUID for a seeded job definition.

    Args:
        job_slug: Stable slug used to derive the seeded UUID

    Returns:
        Deterministic UUID derived from the shared namespace
    """
    return uuid.uuid5(SEED_NAMESPACE_UUID, job_slug)


def build_seeded_timestamp(minute_offset: int) -> datetime:
    """Build a deterministic UTC timestamp for seeded job rows.

    Args:
        minute_offset: Offset in minutes from the shared seed reference timestamp

    Returns:
        Seed timestamp in UTC
    """
    return SEED_REFERENCE_TIMESTAMP + timedelta(minutes=minute_offset)


def build_seed_job_definitions() -> tuple[SeedJobDefinition, ...]:
    """Return the deterministic seed dataset for the jobs table.

    Returns:
        Ordered immutable seeded job definitions
    """
    return (
        SeedJobDefinition(
            id=build_seeded_job_identifier("queued-portfolio-import"),
            input_value="portfolio-import",
            job_type=JobType.ECHO,
            status=JobStatus.QUEUED,
            attempt_count=0,
            maximum_attempt_count=3,
            result=None,
            error_message=None,
            created_at=build_seeded_timestamp(0),
            updated_at=build_seeded_timestamp(0),
        ),
        SeedJobDefinition(
            id=build_seeded_job_identifier("processing-position-reconciliation"),
            input_value="position-reconciliation",
            job_type=JobType.REVERSE,
            status=JobStatus.PROCESSING,
            attempt_count=1,
            maximum_attempt_count=3,
            result=None,
            error_message=None,
            created_at=build_seeded_timestamp(5),
            updated_at=build_seeded_timestamp(11),
        ),
        SeedJobDefinition(
            id=build_seeded_job_identifier("completed-nav-calculation"),
            input_value="nav-calculation",
            job_type=JobType.UPPERCASE,
            status=JobStatus.COMPLETED,
            attempt_count=1,
            maximum_attempt_count=3,
            result="processed:NAV-CALCULATION",
            error_message=None,
            created_at=build_seeded_timestamp(14),
            updated_at=build_seeded_timestamp(19),
        ),
        SeedJobDefinition(
            id=build_seeded_job_identifier("failed-report-publication"),
            input_value="report-publication",
            job_type=JobType.ECHO,
            status=JobStatus.FAILED,
            attempt_count=3,
            maximum_attempt_count=3,
            result=None,
            error_message="simulated downstream publication failure",
            created_at=build_seeded_timestamp(21),
            updated_at=build_seeded_timestamp(27),
        ),
    )


def seed_job_records(
    database_session: Session,
    *,
    truncate_existing_records: bool,
) -> list[JobRecord]:
    """Insert or refresh the deterministic job seed dataset.

    Args:
        database_session: SQLAlchemy session used for persistence work
        truncate_existing_records: Whether to delete existing rows before seeding

    Returns:
        Persisted seeded job records in deterministic order

    Raises:
        RuntimeError: Raised when the database write fails
    """
    seeded_job_definitions = build_seed_job_definitions()

    try:
        if truncate_existing_records:
            database_session.execute(delete(JobRecord))

        persisted_job_records: list[JobRecord] = []
        for seeded_job_definition in seeded_job_definitions:
            persisted_job_record = database_session.merge(
                JobRecord(
                    id=seeded_job_definition.id,
                    input_value=seeded_job_definition.input_value,
                    job_type=seeded_job_definition.job_type,
                    status=seeded_job_definition.status,
                    attempt_count=seeded_job_definition.attempt_count,
                    maximum_attempt_count=seeded_job_definition.maximum_attempt_count,
                    result=seeded_job_definition.result,
                    error_message=seeded_job_definition.error_message,
                    created_at=seeded_job_definition.created_at,
                    updated_at=seeded_job_definition.updated_at,
                )
            )
            persisted_job_records.append(persisted_job_record)

        database_session.commit()

        for persisted_job_record in persisted_job_records:
            database_session.refresh(persisted_job_record)

        return persisted_job_records
    except SQLAlchemyError as database_error:
        database_session.rollback()
        raise RuntimeError("Failed to seed deterministic job records") from database_error


def parse_command_line_arguments() -> argparse.Namespace:
    """Parse command line arguments for the seed command.

    Returns:
        Parsed command line namespace for seed execution
    """
    argument_parser = argparse.ArgumentParser(
        description="Populate the jobs table with deterministic dummy rows.",
    )
    argument_parser.add_argument(
        "--truncate-first",
        action="store_true",
        help="Delete existing job rows before inserting the deterministic seed dataset.",
    )
    return argument_parser.parse_args()


def configure_application_logging() -> None:
    """Configure the logging used by the seed command."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    """Run the deterministic job seed command."""
    configure_application_logging()
    parsed_command_line_arguments = parse_command_line_arguments()

    with database_session_factory() as database_session:
        persisted_job_records = seed_job_records(
            database_session,
            truncate_existing_records=parsed_command_line_arguments.truncate_first,
        )

    logger.info("Seeded %s deterministic job rows", len(persisted_job_records))
    for persisted_job_record in persisted_job_records:
        logger.info(
            "%s | %s | %s",
            persisted_job_record.id,
            persisted_job_record.status.value,
            persisted_job_record.input_value,
        )


if __name__ == "__main__":
    main()