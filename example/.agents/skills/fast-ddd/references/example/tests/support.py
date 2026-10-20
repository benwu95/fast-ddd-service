"""Shared test doubles and builders for the example service."""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx2
from fast_ddd_adapter.infrastructure import OutgoingMessage
from fast_ddd_port.settings import JwtSettings

from app.core.billing.domain.invoice import Customer, CustomerId, InvoiceContent, InvoiceLine

JWT_SETTINGS = JwtSettings(
    issuer="https://issuer.test",
    audience="example-tests",
    jwks_url="https://issuer.test/jwks",
    user_id_claim="sub",
    organization_id_claim="org",
    permissions_claim="scope",
    permissions_format="space_separated",
)
FRONTEND = "https://frontend.test"
NOTIFICATION_URL = "https://notification.test"
ALL_PERMISSIONS = (
    "invoice:read",
    "invoice:create",
    "invoice:update",
    "invoice:delete",
    "invoice:void",
)


def content(
    number: str = "INV-001",
    *,
    customer_id: UUID | None = None,
    lines: tuple[InvoiceLine, ...] = (InvoiceLine("Consulting", 2, Decimal("150.00")),),
    note: str | None = None,
) -> InvoiceContent:
    return InvoiceContent(
        number=number,
        customer=Customer(id=CustomerId(customer_id or uuid4()), name="Acme", tax_id="12345678"),
        lines=lines,
        note=note,
    )


@dataclass
class RecordingPublisher:
    messages: list[OutgoingMessage] = field(default_factory=list[OutgoingMessage])

    async def publish(self, message: OutgoingMessage) -> None:
        self.messages.append(message)

    def event_names(self) -> list[str]:
        return [message.routing_key for message in self.messages]


@dataclass
class NotificationService:
    """Stands in for the notification service; set ``status`` to make it fail."""

    requests: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )
    status: int = 204

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append((request.url.path, json.loads(request.content)))
        return httpx2.Response(self.status)
