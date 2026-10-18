from fast_ddd.event_bus import EventBus
from fast_ddd.events import DomainEvent
from fast_ddd_adapter.infrastructure import task_queue
from fast_ddd_adapter.messaging import integration_message, publish_after_commit

from app.adapter.controller.billing.task_names import SEND_VOID_NOTICE
from app.core.billing.domain.events import (
    InvoiceDeleted,
    InvoiceIssued,
    InvoiceUpdated,
    InvoiceVoided,
)

EXCHANGE = "billing"


async def publish_invoice_event(event: DomainEvent) -> None:
    publish_after_commit(integration_message(event, exchange=EXCHANGE))


async def enqueue_void_notice(event: InvoiceVoided) -> None:
    await task_queue().enqueue(
        SEND_VOID_NOTICE,
        {"invoiceId": str(event.aggregate_id)},
        organization_id=event.organization_id,
    )


def register(bus: EventBus) -> None:
    for event_type in (InvoiceIssued, InvoiceUpdated, InvoiceVoided, InvoiceDeleted):
        bus.subscribe(event_type, publish_invoice_event)
    bus.subscribe(InvoiceVoided, enqueue_void_notice)
