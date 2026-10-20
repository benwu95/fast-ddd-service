from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fast_ddd_port.http import MAX_BATCH_ITEMS
from fast_ddd_port.models import (
    DecimalStr,
    RequestModel,
    ResponseModel,
    Timestamp,
    convert_unless_missing,
    etag_of,
    unset_if_missing,
)
from pydantic import MISSING, Field

from app.adapter.controller.billing.invoice_commands import (
    CreateInvoiceCommand,
    SearchInvoicesQuery,
    UpdateInvoiceCommand,
)
from app.core.billing.domain.invoice import (
    Customer,
    CustomerId,
    Invoice,
    InvoiceContent,
    InvoiceId,
    InvoiceLine,
    InvoiceStatus,
)

type Number = Annotated[str, Field(min_length=1, max_length=30)]
type Note = Annotated[str, Field(max_length=500)]
type Reason = Annotated[str, Field(min_length=1, max_length=200)]
type SearchKeyField = Annotated[
    str, Field(pattern=r"^((starts|ends|equals):)?(number|customerName)$")
]
type SortBy = Annotated[str, Field(pattern=r"^-?(createdAt|number)$")]
type SearchKey = Annotated[str, Field(min_length=1, max_length=100)]


def _snake(name: str) -> str:
    """``starts:customerName`` → ``starts:customer_name``; the repository whitelists names."""
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name)


class CustomerBody(RequestModel):
    id: UUID
    name: Annotated[str, Field(min_length=1, max_length=200)]
    tax_id: Annotated[str, Field(max_length=20)] | None = None

    def to_domain(self) -> Customer:
        return Customer(id=CustomerId(self.id), name=self.name, tax_id=self.tax_id)


class InvoiceLineBody(RequestModel):
    description: Annotated[str, Field(min_length=1, max_length=200)]
    quantity: Annotated[int, Field(gt=0, le=1_000_000)]
    unit_price: Annotated[DecimalStr, Field(ge=0, max_digits=12, decimal_places=2)]

    def to_domain(self) -> InvoiceLine:
        return InvoiceLine(self.description, self.quantity, self.unit_price)


type Lines = Annotated[list[InvoiceLineBody], Field(max_length=100)]


def _lines(lines: list[InvoiceLineBody]) -> tuple[InvoiceLine, ...]:
    return tuple(line.to_domain() for line in lines)


class CreateInvoiceRequest(RequestModel):
    id: UUID | None = None
    number: Number
    customer: CustomerBody
    lines: Lines
    note: Note | None = None

    def to_command(self) -> CreateInvoiceCommand:
        return CreateInvoiceCommand(
            invoice_id=InvoiceId(self.id) if self.id else None,
            content=InvoiceContent(
                number=self.number,
                customer=self.customer.to_domain(),
                lines=_lines(self.lines),
                note=self.note,
            ),
        )


class UpdateInvoiceRequest(RequestModel):
    """Every field is optional; ``customer`` and ``lines`` are replaced as a whole."""

    number: Number | MISSING = MISSING
    customer: CustomerBody | MISSING = MISSING
    lines: Lines | MISSING = MISSING
    note: Note | MISSING | None = MISSING

    def to_command(self, invoice_id: UUID, expected_version: int) -> UpdateInvoiceCommand:
        return UpdateInvoiceCommand(
            invoice_id=InvoiceId(invoice_id),
            expected_version=expected_version,
            number=unset_if_missing(self.number),
            customer=convert_unless_missing(self.customer, CustomerBody.to_domain),
            lines=convert_unless_missing(self.lines, _lines),
            note=unset_if_missing(self.note),
        )


class VoidInvoiceRequest(RequestModel):
    reason: Reason


class BatchVoidItem(RequestModel):
    id: UUID
    etag: str
    reason: Reason


class BatchVoidInvoicesRequest(RequestModel):
    items: Annotated[list[BatchVoidItem], Field(min_length=1, max_length=MAX_BATCH_ITEMS)]


class InvoiceListQuery(RequestModel):
    offset: Annotated[int, Field(ge=0, le=10_000)] = 0
    limit: Annotated[int, Field(ge=1, le=MAX_BATCH_ITEMS)] = 20
    status: list[InvoiceStatus] = Field(default_factory=list[InvoiceStatus], max_length=2)
    customer_id: list[UUID] = Field(default_factory=list[UUID], max_length=MAX_BATCH_ITEMS)
    search_key_field: list[SearchKeyField] = Field(
        default_factory=list[SearchKeyField], max_length=4
    )
    search_key: list[SearchKey] = Field(default_factory=list[SearchKey], max_length=10)
    sort_by: list[SortBy] = Field(default_factory=list[SortBy], max_length=2)

    def to_query(self) -> SearchInvoicesQuery:
        return SearchInvoicesQuery(
            limit=self.limit,
            offset=self.offset,
            statuses=tuple(self.status),
            customer_ids=tuple(CustomerId(id) for id in self.customer_id),
            search_key_fields=tuple(_snake(field) for field in self.search_key_field),
            search_keys=tuple(self.search_key),
            sort_by=tuple(_snake(field) for field in self.sort_by),
        )


class CustomerResponse(ResponseModel):
    id: UUID
    name: str
    tax_id: str | None


class InvoiceLineResponse(ResponseModel):
    description: str
    quantity: int
    unit_price: DecimalStr
    amount: DecimalStr


class InvoiceResponse(ResponseModel):
    id: UUID
    number: str
    customer: CustomerResponse
    lines: list[InvoiceLineResponse]
    total: DecimalStr
    note: str | None
    status: InvoiceStatus
    void_reason: str | None
    voided_at: Timestamp | None
    etag: str
    created_at: Timestamp
    updated_at: Timestamp

    @classmethod
    def from_domain(cls, invoice: Invoice) -> "InvoiceResponse":
        content = invoice.content
        return cls(
            id=invoice.id,
            number=content.number,
            customer=CustomerResponse(
                id=content.customer.id, name=content.customer.name, tax_id=content.customer.tax_id
            ),
            lines=[
                InvoiceLineResponse(
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    amount=line.amount,
                )
                for line in content.lines
            ],
            total=invoice.total.quantize(Decimal("0.01")),
            note=content.note,
            status=invoice.status,
            void_reason=invoice.void_reason,
            voided_at=invoice.voided_at,
            etag=etag_of(invoice.version),
            created_at=invoice.created_at,
            updated_at=invoice.updated_at,
        )
