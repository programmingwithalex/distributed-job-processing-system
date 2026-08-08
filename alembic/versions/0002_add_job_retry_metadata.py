"""
add retry metadata to jobs table

Revision ID: 0002_add_job_retry_metadata
Revises: 0001_create_jobs_table
Create Date: 2026-04-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_add_job_retry_metadata"
down_revision: str | None = "0001_create_jobs_table"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add persisted retry metadata columns to the jobs table."""
    op.add_column(
        "jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "jobs",
        sa.Column("maximum_attempt_count", sa.Integer(), nullable=False, server_default="3"),
    )
    op.alter_column("jobs", "attempt_count", server_default=None)
    op.alter_column("jobs", "maximum_attempt_count", server_default=None)


def downgrade() -> None:
    """Remove persisted retry metadata columns from the jobs table."""
    op.drop_column("jobs", "maximum_attempt_count")
    op.drop_column("jobs", "attempt_count")