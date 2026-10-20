from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, NewType
from uuid import UUID

import pendulum
from fast_ddd.aggregate import AggregateRoot
from fast_ddd.context import User

from app.core.billing.domain.errors import InvoiceAlreadyVoided, InvoiceHasNoLines
from app.core.billing.domain.events import (
    InvoiceDeleted,
    InvoiceIssued,
    InvoiceUpdated,
    InvoiceVoided,
)

InvoiceId = NewType("InvoiceId", UUID)
CustomerId = NewType("CustomerId", UUID)


class InvoiceStatus(StrEnum):
    ACTIVE = "active"
    VOIDED = "voided"


@dataclass(frozen=True, slots=True)
class Customer:
    id: CustomerId
    name: str
    tax_id: str | None = None


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    description: str
    quantity: int
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass(frozen=True, slots=True)
class InvoiceContent:
    """Everything a client decides about an invoice; the rest is lifecycle state."""

    number: str
    customer: Customer
    lines: tuple[InvoiceLine, ...]
    note: str | None = None


class Invoice(AggregateRoot):
    bounded_context: ClassVar[str] = "billing"

    def __init__(
        self,
        *,
        id: InvoiceId,
        organization_id: UUID | None,
        content: InvoiceContent,
        status: InvoiceStatus = InvoiceStatus.ACTIVE,
        void_reason: str | None = None,
        voided_at: pendulum.DateTime | None = None,
        version: int = 0,
        created_at: pendulum.DateTime | None = None,
        updated_at: pendulum.DateTime | None = None,
    ) -> None:
        super().__init__(
            id=id,
            organization_id=organization_id,
            version=version,
            created_at=created_at,
            updated_at=updated_at,
        )
        self.id: InvoiceId = id
        self.content = content
        self.status = status
        self.void_reason = void_reason
        self.voided_at = voided_at

    @property
    def total(self) -> Decimal:
        return sum((line.amount for line in self.content.lines), Decimal(0))

    @classmethod
    def issue(
        cls, *, id: InvoiceId, organization_id: UUID, content: InvoiceContent, doer: User
    ) -> "Invoice":
        _check_lines(content.lines)
        invoice = cls(id=id, organization_id=organization_id, content=content)
        invoice.add_event(
            InvoiceIssued(
                doer=doer,
                number=content.number,
                customer_id=content.customer.id,
                total=invoice.total,
            )
        )
        return invoice

    def update(self, content: InvoiceContent, doer: User) -> None:
        self._ensure_active()
        _check_lines(content.lines)
        if content == self.content:
            return
        self.content = content
        self.add_event(InvoiceUpdated(doer=doer, number=content.number, total=self.total))

    def void(self, reason: str, doer: User) -> None:
        self._ensure_active()
        self.status = InvoiceStatus.VOIDED
        self.void_reason = reason
        self.voided_at = pendulum.now("UTC")
        self.add_event(InvoiceVoided(doer=doer, reason=reason))

    def delete(self, doer: User) -> None:
        """Voided invoices stay for audit; only active ones can be deleted."""
        self._ensure_active()
        self.mark_deleted()
        self.add_event(InvoiceDeleted(doer=doer, number=self.content.number))

    def _ensure_active(self) -> None:
        if self.status is InvoiceStatus.VOIDED:
            raise InvoiceAlreadyVoided(
                invoice_id=self.id, voided_at=self.voided_at or self.updated_at
            )


def _check_lines(lines: Sequence[InvoiceLine]) -> None:
    if not lines:
        raise InvoiceHasNoLines()
