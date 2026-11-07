import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from fast_ddd.context import User, current_organization_id, current_user
from fast_ddd_adapter.infrastructure import infrastructure as kernel_infrastructure
from fast_ddd_adapter.testing import unit_of_work_scope
from fast_ddd_port.tasks import RetryPolicy, TaskEnvelope, TaskRegistry, build_worker
from pgqueuer import PgQueuer
from pgqueuer.types import QueueExecutionMode
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.adapter.controller.billing.invoice_commands import (
    CreateInvoiceCommand,
    UpdateInvoiceCommand,
)
from app.adapter.controller.billing.invoice_controller import BULK_CHUNK_SIZE, InvoiceController
from app.adapter.controller.billing.task_names import (
    DAILY_SUMMARY_SCHEDULE,
    SEND_DAILY_SUMMARY,
    VOID_INVOICES,
)
from app.adapter.repository.billing.invoice_repository import InvoiceRepository
from app.bootstrap import Runtime
from app.core.billing.domain.events import InvoiceVoided
from app.core.billing.domain.invoice import CustomerId, Invoice, InvoiceId, InvoiceStatus
from app.port.task.billing.invoice_tasks import DailySummaryData, VoidInvoicesData
from app.task_worker import build_task_worker
from app.wiring import wire_tasks
from tests.conftest import Infrastructure
from tests.runtime.support import settings
from tests.support import content

type Factory = async_sessionmaker[AsyncSession]

DOER = User(id="user-1")


class Boom(Exception):
    pass


async def drain(connection: asyncpg.Connection, factory: Factory) -> None:
    registry = TaskRegistry()
    wire_tasks(registry)
    worker = build_worker(
        connection, registry, factory, retry=RetryPolicy(max_retries=2, base_delay=timedelta(0))
    )
    await worker.run(mode=QueueExecutionMode.drain, dequeue_timeout=timedelta(seconds=1))


async def jobs(factory: Factory) -> list[tuple[str, str, int]]:
    async with factory() as session:
        rows = await session.execute(
            text("SELECT entrypoint, status::text, attempts FROM pgqueuer ORDER BY id")
        )
        return [(str(r[0]), str(r[1]), int(r[2])) for r in rows]


async def voided_invoice(factory: Factory, organization_id: UUID) -> Invoice:
    controller = InvoiceController()
    with unit_of_work_scope(factory, user=DOER, organization_id=organization_id):
        invoice = await controller.create(CreateInvoiceCommand(None, content()))
        return await controller.void(invoice.id, "duplicate", invoice.version)


def void_notice(invoice: Invoice) -> tuple[str, dict[str, Any]]:
    return (
        f"/notifications/invoice-voided-{invoice.id}",
        {
            "organizationId": str(invoice.organization_id),
            "kind": "invoice_voided",
            "data": {"invoiceId": str(invoice.id), "number": "INV-001", "reason": "duplicate"},
        },
    )


async def test_rolled_back_void_enqueues_nothing(
    session_factory: Factory, infrastructure: Infrastructure, organization_id: UUID
) -> None:
    del infrastructure
    controller = InvoiceController()
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id) as uow:
        invoice = await controller.create(CreateInvoiceCommand(None, content()))

        async def void_then_fail() -> None:
            async with uow:
                await controller.void(invoice.id, "duplicate", invoice.version)
                raise Boom

        with pytest.raises(Boom):
            await void_then_fail()

    assert await jobs(session_factory) == []


async def test_void_notice_is_sent_and_is_idempotent(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    invoice = await voided_invoice(session_factory, organization_id)

    await drain(connection, session_factory)
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        await InvoiceController().send_void_notice(invoice.id)

    assert infrastructure.notifications.requests == [void_notice(invoice)] * 2
    assert await jobs(session_factory) == []


async def test_missing_invoice_fails_once_and_unavailable_service_is_retried(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    gone = await voided_invoice(session_factory, organization_id)
    async with session_factory.begin() as session:
        await session.execute(text("DELETE FROM billing_invoice WHERE id = :id"), {"id": gone.id})
    await drain(connection, session_factory)
    assert await jobs(session_factory) == [("billing.send_void_notice", "failed", 0)]
    assert infrastructure.notifications.requests == []

    infrastructure.notifications.status = 503
    await voided_invoice(session_factory, uuid4())
    await drain(connection, session_factory)

    assert len(infrastructure.notifications.requests) == 3
    assert [status for _, status, _ in await jobs(session_factory)] == ["failed", "failed"]


async def test_transient_failure_retries_the_whole_void_chunk(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    del infrastructure
    customer = uuid4()
    controller = InvoiceController()
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        invoices = [
            await controller.create(
                CreateInvoiceCommand(None, content(f"N-{n}", customer_id=customer))
            )
            for n in range(3)
        ]
    flaky = invoices[1].id
    # Once in the whole-batch phase and once more for the item in the fallback.
    failures_left = 2

    async def fail_twice(event: InvoiceVoided) -> None:
        nonlocal failures_left
        if event.aggregate_id == flaky and failures_left:
            failures_left -= 1
            raise Boom

    kernel_infrastructure().event_bus.subscribe(InvoiceVoided, fail_twice)
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        await controller.enqueue_customer_invoice_voids(CustomerId(customer), "deactivated")

    await drain(connection, session_factory)

    assert failures_left == 0
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        statuses = {(await controller.get(invoice.id)).status for invoice in invoices}
    assert statuses == {InvoiceStatus.VOIDED}
    assert VOID_INVOICES not in {entrypoint for entrypoint, _, _ in await jobs(session_factory)}


async def test_invoice_moved_to_another_customer_after_enqueue_is_not_voided(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    del infrastructure
    customer = CustomerId(uuid4())
    controller = InvoiceController()
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        kept, moved = [
            await controller.create(
                CreateInvoiceCommand(None, content(f"N-{n}", customer_id=customer))
            )
            for n in range(2)
        ]
        await controller.enqueue_customer_invoice_voids(customer, "deactivated")
        other = content(customer_id=uuid4()).customer
        await controller.update(UpdateInvoiceCommand(moved.id, moved.version, customer=other))

    await drain(connection, session_factory)

    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        statuses = [(await controller.get(invoice.id)).status for invoice in (kept, moved)]
    assert statuses == [InvoiceStatus.VOIDED, InvoiceStatus.ACTIVE]


async def test_invoice_cannot_move_to_another_customer_while_its_chunk_is_voided(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
    organization_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del infrastructure
    customer = CustomerId(uuid4())
    controller = InvoiceController()
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        kept, moved = [
            await controller.create(
                CreateInvoiceCommand(None, content(f"N-{n}", customer_id=customer))
            )
            for n in range(2)
        ]
        await controller.enqueue_customer_invoice_voids(customer, "deactivated")
    reread = InvoiceRepository.active_ids_of_customer
    moves_blocked: list[bool] = []

    # A concurrent PATCH between the task's re-read and its void: it must wait for the task.
    async def move_after_reread(
        self: InvoiceRepository, customer_id: CustomerId, **options: Any
    ) -> list[InvoiceId]:
        found = await reread(self, customer_id, **options)
        if options.get("among") is not None:
            try:
                async with session_factory.begin() as other:
                    await other.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    await other.execute(
                        text("UPDATE billing_invoice SET customer_id = :other WHERE id = :id"),
                        {"other": uuid4(), "id": moved.id},
                    )
            except DBAPIError:
                moves_blocked.append(True)
            else:
                moves_blocked.append(False)
        return found

    monkeypatch.setattr(InvoiceRepository, "active_ids_of_customer", move_after_reread)
    await drain(connection, session_factory)

    assert moves_blocked == [True]
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        voided = [await controller.get(invoice.id) for invoice in (kept, moved)]
    assert [(i.status, i.content.customer.id) for i in voided] == [
        (InvoiceStatus.VOIDED, customer)
    ] * 2


async def test_invoice_locked_by_another_transaction_is_voided_once_released(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
    organization_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del infrastructure
    customer = CustomerId(uuid4())
    controller = InvoiceController()
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        free, locked = [
            await controller.create(
                CreateInvoiceCommand(None, content(f"N-{n}", customer_id=customer))
            )
            for n in range(2)
        ]
        await controller.enqueue_customer_invoice_voids(customer, "deactivated")
    reread = InvoiceRepository.active_ids_of_customer

    # Another transaction holds the row while the task re-reads; the task must wait for it.
    async def reread_while_locked(
        self: InvoiceRepository, customer_id: CustomerId, **options: Any
    ) -> list[InvoiceId]:
        if options.get("among") is None:
            return await reread(self, customer_id, **options)
        async with session_factory() as other:
            await other.execute(
                text("SELECT id FROM billing_invoice WHERE id = :id FOR UPDATE"), {"id": locked.id}
            )

            async def release() -> None:
                await asyncio.sleep(0.2)
                await other.commit()

            releasing = asyncio.create_task(release())
            found = await reread(self, customer_id, **options)
            await releasing
        return found

    monkeypatch.setattr(InvoiceRepository, "active_ids_of_customer", reread_while_locked)
    await drain(connection, session_factory)

    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
        statuses = [(await controller.get(invoice.id)).status for invoice in (free, locked)]
    assert statuses == [InvoiceStatus.VOIDED] * 2


@pytest.mark.parametrize("reason", ["", "x" * 201], ids=["empty", "too_long"])
def test_void_invoices_payload_reason_fits_the_column(reason: str) -> None:
    data = {"customerId": str(uuid4()), "invoiceIds": [str(uuid4())], "reason": reason}
    with pytest.raises(ValidationError):
        VoidInvoicesData.model_validate(data)


@pytest.mark.parametrize("count", [0, BULK_CHUNK_SIZE + 1])
def test_void_invoices_payload_holds_one_chunk(count: int) -> None:
    data = {"customerId": str(uuid4()), "invoiceIds": [str(uuid4()) for _ in range(count)]}
    with pytest.raises(ValidationError):
        VoidInvoicesData.model_validate({**data, "reason": "deactivated"})


async def test_daily_summary_fans_out_per_organization(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
) -> None:
    first, second = uuid4(), uuid4()
    controller = InvoiceController()
    for organization_id, count in ((first, 2), (second, 1)):
        with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
            for i in range(count):
                await controller.create(CreateInvoiceCommand(None, content(f"N-{i}")))

    with unit_of_work_scope(session_factory, user=User(id="schedule"), organization_id=None):
        await controller.enqueue_daily_summaries()
        await controller.enqueue_daily_summaries()
    assert [name for name, _, _ in await jobs(session_factory)] == [
        "billing.send_daily_summary"
    ] * 2

    await drain(connection, session_factory)

    sent = {
        body["organizationId"]: (body["kind"], body["data"]["count"], body["data"]["amount"])
        for _, body in infrastructure.notifications.requests
    }
    assert sent == {
        str(first): ("daily_invoice_summary", 2, "600.00"),
        str(second): ("daily_invoice_summary", 1, "300.00"),
    }


def test_worker_registers_tasks_and_the_schedule(
    session_factory: Factory, connection: asyncpg.Connection
) -> None:
    registry = TaskRegistry()
    wire_tasks(registry)
    worker = build_worker(connection, registry, session_factory)

    assert set(registry.tasks) == {
        "billing.send_void_notice",
        "billing.send_daily_summary",
        "billing.void_invoices",
    }
    schedules = {str(key.entrypoint) for key in worker.sm.registry}
    assert schedules == {DAILY_SUMMARY_SCHEDULE}


async def test_service_worker_composes_real_registry_and_runtime_session_factory(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
    engine: AsyncEngine,
    organization_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fast_ddd_adapter.messaging import create_broker

    import app.task_worker as entrypoint

    resources = Runtime(
        settings(),
        engine,
        session_factory,
        create_broker("amqp://guest:guest@localhost/"),
    )
    calls: list[tuple[asyncpg.Connection, TaskRegistry, Factory]] = []

    def compose(conn: asyncpg.Connection, registry: TaskRegistry, factory: Factory) -> PgQueuer:
        calls.append((conn, registry, factory))
        return build_worker(conn, registry, factory)

    monkeypatch.setattr(entrypoint, "build_worker", compose)
    worker = build_task_worker(resources, connection)
    assert calls[0][0] is connection
    assert calls[0][2] is session_factory
    assert set(calls[0][1].tasks) == {
        "billing.send_void_notice",
        "billing.send_daily_summary",
        "billing.void_invoices",
    }
    assert {str(key.entrypoint) for key in worker.sm.registry} == {DAILY_SUMMARY_SCHEDULE}
    invoice = await voided_invoice(session_factory, organization_id)
    await worker.run(mode=QueueExecutionMode.drain, dequeue_timeout=timedelta(seconds=1))
    assert infrastructure.notifications.requests == [void_notice(invoice)]
    assert await jobs(session_factory) == []


async def test_external_success_then_local_commit_failure_resends_the_same_notification_key(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
    organization_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoice = await voided_invoice(session_factory, organization_id)
    original_commit = AsyncSession.commit
    failed_once = False

    async def fail_first_completion(session: AsyncSession) -> None:
        nonlocal failed_once
        if infrastructure.notifications.requests and not failed_once:
            failed_once = True
            raise OSError("local commit failed after remote success")
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", fail_first_completion)
    await drain(connection, session_factory)
    assert failed_once
    assert infrastructure.notifications.requests == [void_notice(invoice)] * 2
    assert len({key for key, _ in infrastructure.notifications.requests}) == 1
    assert await jobs(session_factory) == []


async def test_due_daily_summary_runs_in_full_worker_and_keeps_organization_fanout(
    session_factory: Factory,
    infrastructure: Infrastructure,
    connection: asyncpg.Connection,
) -> None:
    organizations = [uuid4(), uuid4()]
    controller = InvoiceController()
    for organization_id in organizations:
        with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id):
            await controller.create(CreateInvoiceCommand(None, content()))
    registry = TaskRegistry()
    wire_tasks(registry)
    expression, original = registry.schedules[DAILY_SUMMARY_SCHEDULE]
    contexts: list[tuple[str, UUID | None]] = []

    async def scheduled() -> None:
        contexts.append((current_user().id, current_organization_id()))
        await original()

    registry.schedules[DAILY_SUMMARY_SCHEDULE] = (expression, scheduled)
    original_handler = registry.tasks[SEND_DAILY_SUMMARY].handler

    async def send_and_stop(envelope: TaskEnvelope, data: DailySummaryData) -> None:
        await original_handler(envelope, data)
        if len(infrastructure.notifications.requests) == 2:
            worker.shutdown.set()

    registry.task(SEND_DAILY_SUMMARY, DailySummaryData, send_and_stop)
    worker = build_worker(connection, registry, session_factory)
    key = next(iter(worker.sm.registry))
    await worker.sm.queries.insert_schedule({key: timedelta(seconds=-1)})
    async with asyncio.timeout(10):
        await worker.run(dequeue_timeout=timedelta(seconds=0.05))
    assert contexts == [(f"schedule:{DAILY_SUMMARY_SCHEDULE}", None)]
    assert {body["organizationId"] for _, body in infrastructure.notifications.requests} == {
        str(organization_id) for organization_id in organizations
    }
    assert len(infrastructure.notifications.requests) == 2
    assert await jobs(session_factory) == []
