"""
Create the PostgreSQL dispatch-outbox table and its index for pending execution commands.
Store job references and broker-delivery metadata so newly submitted jobs can commit
their dispatch records before any attempt to contact RabbitMQ.
Backfill eligible existing jobs during upgrade so the new dispatcher can recover
work created before transactional command delivery was introduced.
This migration changes application database storage only; it neither sends messages
to RabbitMQ nor creates Kafka topics, and downgrade removes the dispatch records.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_job_dispatch_outbox"
down_revision: str | None = "0008_event_partition_offsets"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create the dispatch outbox and recover queued jobs from older releases."""
    op.create_table(
        "job_dispatch_outbox",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_job_dispatch_outbox_pending",
        "job_dispatch_outbox",
        ["next_attempt_at", "created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    op.execute(
        "INSERT INTO job_dispatch_outbox (job_id) "
        "SELECT id FROM jobs WHERE status IN ('queued', 'processing')"
    )


def downgrade() -> None:
    """Remove execution delivery records."""
    op.drop_table("job_dispatch_outbox")
