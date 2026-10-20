from decimal import Decimal
from uuid import UUID

import pendulum
from fast_ddd_adapter.orm import Base
from fast_ddd_adapter.repository import AggregateModel
from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship


class InvoiceModel(AggregateModel):
    __tablename__ = "billing_invoice"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        Index("ix_billing_invoice_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_billing_invoice_organization_id_customer_id", "organization_id", "customer_id"),
    )

    number: Mapped[str] = mapped_column(String(30))
    customer_id: Mapped[UUID]
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_tax_id: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))
    void_reason: Mapped[str | None] = mapped_column(String(200))
    voided_at: Mapped[pendulum.DateTime | None]
    lines: Mapped[list["InvoiceLineModel"]] = relationship(
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InvoiceLineModel.position",
    )


class InvoiceLineModel(Base):
    __tablename__ = "billing_invoice_line"

    invoice_id: Mapped[UUID] = mapped_column(
        ForeignKey("billing_invoice.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
