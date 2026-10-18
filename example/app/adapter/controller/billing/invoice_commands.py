from dataclasses import dataclass

from fast_ddd_adapter.commands import UNSET, Unset

from app.core.billing.domain.invoice import (
    Customer,
    CustomerId,
    InvoiceContent,
    InvoiceId,
    InvoiceLine,
    InvoiceStatus,
)


@dataclass(frozen=True, slots=True)
class CreateInvoiceCommand:
    invoice_id: InvoiceId | None
    content: InvoiceContent


@dataclass(frozen=True, slots=True)
class UpdateInvoiceCommand:
    """PATCH: ``UNSET`` keeps the current value; ``note=None`` clears the note."""

    invoice_id: InvoiceId
    expected_version: int
    number: str | Unset = UNSET
    customer: Customer | Unset = UNSET
    lines: tuple[InvoiceLine, ...] | Unset = UNSET
    note: str | Unset | None = UNSET


@dataclass(frozen=True, slots=True)
class SearchInvoicesQuery:
    limit: int
    offset: int = 0
    statuses: tuple[InvoiceStatus, ...] = ()
    customer_ids: tuple[CustomerId, ...] = ()
    search_key_fields: tuple[str, ...] = ()
    search_keys: tuple[str, ...] = ()
    sort_by: tuple[str, ...] = ()
