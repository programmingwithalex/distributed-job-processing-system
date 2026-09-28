"""add job history projection

Revision ID: 0007_add_job_history_projection
Revises: 0006_add_job_event_outbox
Create Date: 2026-09-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_add_job_history_projection"
down_revision: str | None = "0006_add_job_event_outbox"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create the idempotent PostgreSQL projection used by job history reads."""
    op.create_table(
        "job_history",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("job_id", "sequence_number", name="uq_job_history_job_sequence"),
    )
    op.create_index("ix_job_history_job_id", "job_history", ["job_id"])


def downgrade() -> None:
    """Remove the projected job history table."""
    op.drop_index("ix_job_history_job_id", table_name="job_history")
    op.drop_table("job_history")