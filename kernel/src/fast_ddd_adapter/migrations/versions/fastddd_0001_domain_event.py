"""create domain_event

Revision ID: fastddd_0001
Revises:
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fastddd_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("fast_ddd",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domain_event",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("aggregate_type", sa.String(length=200), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=True),
        sa.Column("doer", postgresql.JSONB(), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("parent_event_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_domain_event")),
    )
    op.create_index(
        "ix_domain_event_aggregate",
        "domain_event",
        ["organization_id", "aggregate_type", "aggregate_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_domain_event_aggregate", table_name="domain_event")
    op.drop_table("domain_event")
