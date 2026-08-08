"""
add dead-lettered job status

Revision ID: 0004_add_dead_lettered_status
Revises: 0003_add_job_type_to_jobs_table
Create Date: 2026-08-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_add_dead_lettered_status"
down_revision: str | None = "0003_add_job_type_to_jobs_table"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add the dead-lettered status and its transition timestamp."""
    op.execute("ALTER TYPE job_status ADD VALUE 'dead_lettered'")
    op.add_column(
        "jobs",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Map dead-lettered jobs to failed and restore the previous enum."""
    op.execute("UPDATE jobs SET status = 'failed' WHERE status = 'dead_lettered'")
    op.drop_column("jobs", "dead_lettered_at")
    op.execute("ALTER TABLE jobs ALTER COLUMN status TYPE VARCHAR USING status::text")
    op.execute("DROP TYPE job_status")
    op.execute("CREATE TYPE job_status AS ENUM ('queued', 'processing', 'completed', 'failed')")
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN status TYPE job_status USING status::job_status"
    )