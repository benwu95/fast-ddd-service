from uuid import UUID, uuid4

from fast_ddd.batch import BatchItem
from fast_ddd.context import User
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.infrastructure import configure
from fast_ddd_adapter.orm import DomainEventModel
from fast_ddd_adapter.testing import count_statements, unit_of_work_scope
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.adapter.controller.billing.invoice_commands import CreateInvoiceCommand
from app.adapter.controller.billing.invoice_controller import InvoiceController
from app.core.billing.domain.invoice import CustomerId, Invoice, InvoiceStatus
from tests.conftest import Infrastructure
from tests.support import content

type Factory = async_sessionmaker[AsyncSession]

DOER = User(id="user-1")


async def create_invoices(
    factory: Factory, organization_id: UUID, count: int, *, customer: UUID | None = None
) -> list[Invoice]:
    controller = InvoiceController()
    with unit_of_work_scope(factory, user=DOER, organization_id=organization_id):
        return [
            await controller.create(
                CreateInvoiceCommand(None, content(f"N-{uuid4().hex[:8]}", customer_id=customer))
            )
            for _ in range(count)
        ]


async def test_batch_void_round_trips_do_not_grow_with_the_batch(
    session_factory: Factory, engine: AsyncEngine, organization_id: UUID
) -> None:
    # Without handlers: an event handler that does I/O per event grows with N by design.
    configure(session_factory=session_factory, event_bus=EventBus())

    async def statements_to_void(count: int) -> int:
        invoices = await create_invoices(session_factory, organization_id, count)
        items = [BatchItem(invoice.id, "r", expected_version=1) for invoice in invoices]
        with (
            unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id),
            count_statements(engine) as counter,
        ):
            outcome = await InvoiceController().void_many(items)
        assert all(isinstance(result, Invoice) for result in outcome.results.values())
        return counter.count

    assert await statements_to_void(1) == await statements_to_void(50)


async def test_customer_invoices_are_voided_in_chunks_and_skip_voided_ones(
    session_factory: Factory, infrastructure: Infrastructure, organization_id: UUID
) -> None:
    del infrastructure
    customer = CustomerId(UUID(int=7))
    invoices = await create_invoices(session_factory, organization_id, 3, customer=customer)
    others = await create_invoices(session_factory, organization_id, 1)
    controller = InvoiceController()
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        await controller.void(invoices[0].id, "earlier", 1)
        await controller.void_customer_invoices(customer, "customer deactivated")
        statuses = [(await controller.get(i.id)).status for i in [*invoices, *others]]

    assert statuses == [InvoiceStatus.VOIDED] * 3 + [InvoiceStatus.ACTIVE]
    async with session_factory() as session:
        voided_events = await session.scalar(
            select(func.count())
            .select_from(DomainEventModel)
            .where(DomainEventModel.name == "InvoiceVoided")
        )
    assert voided_events == 3
