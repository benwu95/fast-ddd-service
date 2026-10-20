from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

import pendulum
from fast_ddd.errors import DomainError, ErrorKind


@dataclass
class InvoiceAlreadyVoided(DomainError):
    code: ClassVar[str] = "billing.invoice.already_voided"
    kind: ClassVar[ErrorKind] = ErrorKind.CONFLICT
    message: ClassVar[str] = "Invoice {invoiceId} was voided at {voidedAt}"

    invoice_id: UUID
    voided_at: pendulum.DateTime


@dataclass
class InvoiceHasNoLines(DomainError):
    code: ClassVar[str] = "billing.invoice.no_lines"
    kind: ClassVar[ErrorKind] = ErrorKind.INVALID
    message: ClassVar[str] = "An invoice needs at least one line"


@dataclass
class InvoiceNumberTaken(DomainError):
    code: ClassVar[str] = "billing.invoice.number_taken"
    kind: ClassVar[ErrorKind] = ErrorKind.CONFLICT
    message: ClassVar[str] = "Another invoice of this organization already uses this number"
