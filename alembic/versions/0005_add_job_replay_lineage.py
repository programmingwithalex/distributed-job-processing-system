"""
add job replay lineage

Revision ID: 0005_add_job_replay_lineage
Revises: 0004_add_dead_lettered_status
Create Date: 2026-08-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_add_job_replay_lineage"
down_revision: str | None = "0004_add_dead_lettered_status"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add the replay lineage foreign key and supporting index."""
    op.add_column(
        "jobs",
        sa.Column("replayed_from_job_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_jobs_replayed_from_job_id_jobs",
        "jobs",
        "jobs",
        ["replayed_from_job_id"],
        ["id"],
    )
    op.create_index(
        "ix_jobs_replayed_from_job_id",
        "jobs",
        ["replayed_from_job_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the replay lineage index, foreign key, and column."""
    op.drop_index("ix_jobs_replayed_from_job_id", table_name="jobs")
    op.drop_constraint(
        "fk_jobs_replayed_from_job_id_jobs",
        "jobs",
        type_="foreignkey",
    )
    op.drop_column("jobs", "replayed_from_job_id")