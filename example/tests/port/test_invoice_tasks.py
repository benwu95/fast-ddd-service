import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from fast_ddd.context import User, current_organization_id, current_user
from fast_ddd_adapter.testing import unit_of_work_scope
from fast_ddd_port.tasks import RetryPolicy, TaskEnvelope, TaskRegistry, build_worker
from pgqueuer import PgQueuer
from pgqueuer.types import QueueExecutionMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.adapter.controller.billing.invoice_commands import CreateInvoiceCommand
from app.adapter.controller.billing.invoice_controller import InvoiceController
from app.adapter.controller.billing.task_names import DAILY_SUMMARY_SCHEDULE, SEND_DAILY_SUMMARY
from app.bootstrap import Runtime
from app.core.billing.domain.invoice import Invoice
from app.port.task.billing.invoice_tasks import DailySummaryData
from app.task_worker import build_task_worker, driver_dsn
from app.wiring import wire_tasks
from tests.conftest import Infrastructure
from tests.support import content
from tests.test_worker_lifecycle import settings

type Factory = async_sessionmaker[AsyncSession]

DOER = User(id="user-1")


class Boom(Exception):
    pass


@pytest.fixture
async def connection(database_url: str) -> AsyncGenerator[asyncpg.Connection]:
    connection = await asyncpg.connect(driver_dsn(database_url))
    yield connection
    await connection.close()


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

    assert set(registry.tasks) == {"billing.send_void_notice", "billing.send_daily_summary"}
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
