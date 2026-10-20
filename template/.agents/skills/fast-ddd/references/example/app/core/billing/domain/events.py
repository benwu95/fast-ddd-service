from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from fast_ddd.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class InvoiceIssued(DomainEvent):
    number: str
    customer_id: UUID
    total: Decimal


@dataclass(frozen=True, kw_only=True)
class InvoiceUpdated(DomainEvent):
    number: str
    total: Decimal


@dataclass(frozen=True, kw_only=True)
class InvoiceVoided(DomainEvent):
    reason: str


@dataclass(frozen=True, kw_only=True)
class InvoiceDeleted(DomainEvent):
    number: str
