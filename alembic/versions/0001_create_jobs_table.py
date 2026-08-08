"""
create jobs table

Revision ID: 0001_create_jobs_table
Revises:
Create Date: 2026-04-19 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_create_jobs_table"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


job_status = postgresql.ENUM(
    "queued",
    "processing",
    "completed",
    "failed",
    name="job_status",
    create_type=False,
)


def upgrade() -> None:
    """Create the initial job status enum and jobs table."""
    job_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("input_value", sa.String(length=255), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    """Drop the initial jobs table and supporting job status enum."""
    op.drop_table("jobs")
    job_status.drop(op.get_bind(), checkfirst=True)
