"""
add job type to jobs table

Revision ID: 0003_add_job_type_to_jobs_table
Revises: 0002_add_job_retry_metadata
Create Date: 2026-04-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_add_job_type_to_jobs_table"
down_revision: str | None = "0002_add_job_retry_metadata"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


job_type = postgresql.ENUM(
    "echo",
    "reverse",
    "uppercase",
    name="job_type",
    create_type=False,
)


def upgrade() -> None:
    """Add persisted job type support to the jobs table."""
    job_type.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "jobs",
        sa.Column("job_type", job_type, nullable=False, server_default="echo"),
    )
    op.alter_column("jobs", "job_type", server_default=None)


def downgrade() -> None:
    """Remove persisted job type support from the jobs table."""
    op.drop_column("jobs", "job_type")
    job_type.drop(op.get_bind(), checkfirst=True)