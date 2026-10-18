"""create processed_message (inbox)

Revision ID: fastddd_0002
Revises: fastddd_0001
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fastddd_0002"
down_revision: str | None = "fastddd_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processed_message",
        sa.Column("subscriber", sa.String(length=200), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("subscriber", "event_id", name=op.f("pk_processed_message")),
    )


def downgrade() -> None:
    op.drop_table("processed_message")
