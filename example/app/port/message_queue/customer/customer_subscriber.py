from uuid import UUID

from fast_ddd_port.models import MessageModel
from fast_ddd_port.subscriber import Envelope, kernel_queue, subscribe
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapter.controller.billing.invoice_controller import InvoiceController
from app.core.billing.domain.invoice import CustomerId

CUSTOMER_EXCHANGE = "customer"
CUSTOMER_DEACTIVATED_QUEUE = "billing.customer-deactivated"

controller = InvoiceController()


class CustomerDeactivatedData(MessageModel):
    customer_id: UUID


async def handle_customer_deactivated(_: Envelope, data: CustomerDeactivatedData) -> None:
    await controller.void_customer_invoices(
        CustomerId(data.customer_id), reason="customer deactivated"
    )


def register(broker: RabbitBroker, session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    """Subscribe this context's consumers; returns their queue names (for DLQ declaration)."""
    subscribe(
        broker,
        name=CUSTOMER_DEACTIVATED_QUEUE,
        queue=kernel_queue(CUSTOMER_DEACTIVATED_QUEUE, routing_key="CustomerDeactivated"),
        exchange=CUSTOMER_EXCHANGE,
        payload=CustomerDeactivatedData,
        handler=handle_customer_deactivated,
        session_factory=session_factory,
    )
    return [CUSTOMER_DEACTIVATED_QUEUE]
