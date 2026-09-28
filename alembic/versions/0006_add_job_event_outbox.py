"""add job lifecycle event outbox

Revision ID: 0006_add_job_event_outbox
Revises: 0005_add_job_replay_lineage
Create Date: 2026-09-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006_add_job_event_outbox"
down_revision: str | None = "0005_add_job_replay_lineage"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create durable storage for job lifecycle events awaiting Kafka delivery."""
    op.add_column(
        "jobs",
        sa.Column("lifecycle_event_sequence", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_table(
        "job_event_outbox",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("message_key", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint(
            "job_id",
            "sequence_number",
            name="uq_job_event_outbox_job_sequence",
        ),
    )
    op.create_index("ix_job_event_outbox_job_id", "job_event_outbox", ["job_id"])
    op.create_index(
        "ix_job_event_outbox_pending",
        "job_event_outbox",
        ["published_at", "next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    """Remove the job lifecycle event outbox table."""
    op.drop_index("ix_job_event_outbox_pending", table_name="job_event_outbox")
    op.drop_index("ix_job_event_outbox_job_id", table_name="job_event_outbox")
    op.drop_table("job_event_outbox")
    op.drop_column("jobs", "lifecycle_event_sequence")