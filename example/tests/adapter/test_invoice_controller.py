import json
from uuid import UUID, uuid4

import pytest
from fast_ddd.batch import BatchItem
from fast_ddd.context import User
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.infrastructure import configure
from fast_ddd_adapter.orm import DomainEventModel
from fast_ddd_adapter.testing import count_statements, unit_of_work_scope
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.adapter.controller.billing.invoice_commands import CreateInvoiceCommand
from app.adapter.controller.billing.invoice_controller import BULK_CHUNK_SIZE, InvoiceController
from app.adapter.controller.billing.task_names import VOID_INVOICES
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


async def test_void_invoices_skips_voided_and_missing_ones(
    session_factory: Factory,
    infrastructure: Infrastructure,
    organization_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    del infrastructure
    customer = CustomerId(UUID(int=7))
    voided, deleted, *targeted, untouched = await create_invoices(
        session_factory, organization_id, 5, customer=customer
    )
    controller = InvoiceController()
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        await controller.void(voided.id, "earlier", 1)
        await controller.delete(deleted.id, 1)
        await controller.void_invoices(
            customer,
            [voided.id, deleted.id, *(invoice.id for invoice in targeted)],
            "customer deactivated",
        )
        statuses = [(await controller.get(i.id)).status for i in [voided, *targeted, untouched]]

    assert statuses == [InvoiceStatus.VOIDED] * 3 + [InvoiceStatus.ACTIVE]
    warnings = [r.getMessage() for r in caplog.records if "was not voided" in r.getMessage()]
    assert {message.split()[1] for message in warnings} == {str(voided.id), str(deleted.id)}
    async with session_factory() as session:
        voided_events = await session.scalar(
            select(func.count())
            .select_from(DomainEventModel)
            .where(DomainEventModel.name == "InvoiceVoided")
        )
    assert voided_events == 3


async def test_customer_invoices_are_enqueued_in_chunks(
    session_factory: Factory, infrastructure: Infrastructure, organization_id: UUID
) -> None:
    del infrastructure
    customer = CustomerId(UUID(int=7))
    active = await create_invoices(session_factory, organization_id, 251, customer=customer)
    await create_invoices(session_factory, organization_id, 1)
    controller = InvoiceController()
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        await controller.void(active.pop().id, "earlier", 1)
        await controller.enqueue_customer_invoice_voids(customer, "customer deactivated")

    async with session_factory() as session:
        payloads = await session.scalars(
            text("SELECT payload FROM pgqueuer WHERE entrypoint = :name ORDER BY id"),
            {"name": VOID_INVOICES},
        )
        bodies = [json.loads(payload) for payload in payloads]
    assert {body["organizationId"] for body in bodies} == {str(organization_id)}
    assert {body["data"]["reason"] for body in bodies} == {"customer deactivated"}
    assert {body["data"]["customerId"] for body in bodies} == {str(customer)}
    chunks = [body["data"]["invoiceIds"] for body in bodies]
    assert sorted(len(chunk) for chunk in chunks) == [50, BULK_CHUNK_SIZE, BULK_CHUNK_SIZE]
    enqueued = [invoice_id for chunk in chunks for invoice_id in chunk]
    assert sorted(enqueued) == sorted(str(invoice.id) for invoice in active)
