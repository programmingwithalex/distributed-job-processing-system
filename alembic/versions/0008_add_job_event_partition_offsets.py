"""add Kafka partition offsets for operations metrics

Revision ID: 0008_event_partition_offsets
Revises: 0007_add_job_history_projection
Create Date: 2026-09-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_event_partition_offsets"
down_revision: str | None = "0007_add_job_history_projection"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create per-partition offsets for published and projected Kafka events."""
    op.create_table(
        "job_event_partition_offsets",
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("partition_number", sa.Integer(), nullable=False),
        sa.Column("latest_published_offset", sa.Integer(), nullable=True),
        sa.Column("latest_consumed_offset", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("topic", "partition_number"),
    )


def downgrade() -> None:
    """Remove persisted Kafka partition offsets."""
    op.drop_table("job_event_partition_offsets")