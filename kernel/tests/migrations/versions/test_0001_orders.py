from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "kernel_test_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("kernel_test",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kernel_test_order",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kernel_test_order")),
        sa.UniqueConstraint("code", name=op.f("uq_kernel_test_order_code")),
    )
    op.create_index(
        op.f("ix_kernel_test_order_organization_id"), "kernel_test_order", ["organization_id"]
    )
    op.create_table(
        "kernel_test_order_line",
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("line_id", name=op.f("pk_kernel_test_order_line")),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["kernel_test_order.id"],
            name=op.f("fk_kernel_test_order_line_order_id_kernel_test_order"),
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "kernel_test_order_archive",
        sa.Column("archive_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("event_name", sa.String(200), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.PrimaryKeyConstraint("archive_id", name=op.f("pk_kernel_test_order_archive")),
    )
    op.create_index(op.f("ix_kernel_test_order_archive_id"), "kernel_test_order_archive", ["id"])


def downgrade() -> None:
    op.drop_table("kernel_test_order_archive")
    op.drop_table("kernel_test_order_line")
    op.drop_table("kernel_test_order")
