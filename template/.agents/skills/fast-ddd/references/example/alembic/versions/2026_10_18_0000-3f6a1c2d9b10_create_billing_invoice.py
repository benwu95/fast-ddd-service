"""create billing invoice

Revision ID: 3f6a1c2d9b10
Revises:
Create Date: 2026-10-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f6a1c2d9b10"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("service",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_invoice",
        sa.Column("number", sa.String(length=30), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("customer_tax_id", sa.String(length=20), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("void_reason", sa.String(length=200), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_invoice")),
        sa.UniqueConstraint(
            "organization_id", "number", name=op.f("uq_billing_invoice_organization_id_number")
        ),
    )
    op.create_index(
        op.f("ix_billing_invoice_organization_id"), "billing_invoice", ["organization_id"]
    )
    op.create_index(
        "ix_billing_invoice_organization_id_created_at",
        "billing_invoice",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_billing_invoice_organization_id_customer_id",
        "billing_invoice",
        ["organization_id", "customer_id"],
    )
    op.create_table(
        "billing_invoice_line",
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["billing_invoice.id"],
            name=op.f("fk_billing_invoice_line_invoice_id_billing_invoice"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("invoice_id", "position", name=op.f("pk_billing_invoice_line")),
    )


def downgrade() -> None:
    op.drop_table("billing_invoice_line")
    op.drop_index("ix_billing_invoice_organization_id_customer_id", table_name="billing_invoice")
    op.drop_index("ix_billing_invoice_organization_id_created_at", table_name="billing_invoice")
    op.drop_index(op.f("ix_billing_invoice_organization_id"), table_name="billing_invoice")
    op.drop_table("billing_invoice")
