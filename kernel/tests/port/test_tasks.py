import asyncio
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from opentelemetry.trace import SpanKind
from pgqueuer import PgQueuer
from pgqueuer.types import QueueExecutionMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd.context import (
    User,
    current_organization_id,
    current_trace_id,
    current_user,
)
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.controller import execute
from fast_ddd_adapter.infrastructure import (
    NotConfiguredError,
    configure,
    system_context,
    task_queue,
)
from fast_ddd_adapter.tasks import PgQueuerTaskQueue
from fast_ddd_adapter.testing import unit_of_work_scope
from fast_ddd_port.models import MessageModel, Timestamp
from fast_ddd_port.tasks import (
    RetryPolicy,
    TaskEnvelope,
    TaskRegistry,
    TaskRejectedError,
    build_worker,
)
from tests.adapter.models import OrderAlreadyVoided, OrderModel, OrderRepository
from tests.adapter.use_cases import OrderUseCase
from tests.telemetry import Telemetry, span_trace_id

type Factory = async_sessionmaker[AsyncSession]


class ExportData(MessageModel):
    report: str


class TimestampData(MessageModel):
    payload_timestamp: Timestamp


@dataclass
class Calls:
    seen: list[tuple[str, UUID | None, str | None]] = field(
        default_factory=list[tuple[str, UUID | None, str | None]]
    )
    failures_left: int = 0


@pytest.fixture
async def connection(database_url: str) -> AsyncGenerator[asyncpg.Connection]:
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
    connection = await asyncpg.connect(dsn)
    yield connection
    await connection.close()


@pytest.fixture
def queue(session_factory: Factory) -> PgQueuerTaskQueue:
    task_queue = PgQueuerTaskQueue()
    configure(session_factory=session_factory, event_bus=EventBus(), task_queue=task_queue)
    return task_queue


async def statuses(factory: Factory) -> list[tuple[str, int]]:
    async with factory() as session:
        rows = await session.execute(
            text("SELECT status::text, attempts FROM pgqueuer ORDER BY id")
        )
        return [(str(row[0]), int(row[1])) for row in rows]


async def enqueue(
    factory: Factory,
    queue: PgQueuerTaskQueue,
    org: UUID,
    report: str,
    *,
    fail: bool = False,
    trace_id: str = "trace-1",
) -> None:
    async def work() -> None:
        assert task_queue() is queue
        await task_queue().enqueue("export", {"report": report}, organization_id=org)
        if fail:
            raise ZeroDivisionError

    with unit_of_work_scope(factory, user=User(id="u"), organization_id=org, trace_id=trace_id):
        await execute(work)


def registry_with(calls: Calls) -> TaskRegistry:
    registry = TaskRegistry()

    async def export(envelope: TaskEnvelope, data: ExportData) -> None:
        calls.seen.append((data.report, current_organization_id(), current_trace_id()))
        assert envelope.organization_id == current_organization_id()
        if data.report == "reject":
            raise OrderAlreadyVoided(order_id=uuid4())
        if calls.failures_left > 0:
            calls.failures_left -= 1
            raise RuntimeError("temporary")

    registry.task("export", ExportData, export)
    return registry


async def drain(connection: asyncpg.Connection, registry: TaskRegistry, factory: Factory) -> None:
    worker = build_worker(
        connection, registry, factory, retry=RetryPolicy(max_retries=2, base_delay=timedelta(0))
    )
    await worker.run(mode=QueueExecutionMode.drain, dequeue_timeout=timedelta(seconds=1))


def outcomes(telemetry: Telemetry) -> dict[str, float]:
    return {
        outcome: telemetry.total("fast_ddd.task.duration", task="export", outcome=outcome)
        for outcome in ("success", "retried", "failed")
    }


def delta(after: dict[str, float], before: dict[str, float]) -> dict[str, float]:
    return {key: after[key] - before[key] for key in after if after[key] != before[key]}


def test_task_queue_must_be_configured(session_factory: Factory) -> None:
    configure(session_factory=session_factory, event_bus=EventBus())
    with pytest.raises(NotConfiguredError):
        task_queue()


async def test_enqueue_is_part_of_the_callers_transaction(
    session_factory: Factory, queue: PgQueuerTaskQueue, organization_id: UUID, telemetry: Telemetry
) -> None:
    before = telemetry.total("fast_ddd.task.enqueued", task="export")
    await enqueue(session_factory, queue, organization_id, "kept")
    with pytest.raises(ZeroDivisionError):
        await enqueue(session_factory, queue, organization_id, "rolled-back", fail=True)

    assert await statuses(session_factory) == [("queued", 0)]
    assert telemetry.total("fast_ddd.task.enqueued", task="export") - before == 1


async def test_duplicate_dedupe_key_is_skipped_without_aborting_the_transaction(
    session_factory: Factory, queue: PgQueuerTaskQueue, organization_id: UUID
) -> None:
    assert task_queue() is queue

    async def work() -> list[bool]:
        results = [
            await task_queue().enqueue(
                "export", {"report": name}, organization_id=organization_id, dedupe_key="monthly"
            )
            for name in ("first", "second")
        ]
        await task_queue().enqueue("export", {"report": "other"}, organization_id=organization_id)
        return results

    with unit_of_work_scope(session_factory, user=User(id="u"), organization_id=organization_id):
        assert await execute(work) == [True, False]

    assert await statuses(session_factory) == [("queued", 0), ("queued", 0)]


async def test_worker_runs_job_with_task_context(
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    calls = Calls()
    await enqueue(session_factory, queue, organization_id, "monthly")

    await drain(connection, registry_with(calls), session_factory)

    assert calls.seen == [("monthly", organization_id, "trace-1")]
    assert await statuses(session_factory) == []


async def test_worker_continues_the_enqueuers_trace(
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
    connection: asyncpg.Connection,
    organization_id: UUID,
    telemetry: Telemetry,
) -> None:
    calls = Calls()
    with span_trace_id("request") as trace_id:
        await enqueue(session_factory, queue, organization_id, "traced", trace_id=trace_id)

    await drain(connection, registry_with(calls), session_factory)

    assert calls.seen == [("traced", organization_id, trace_id)]
    task_spans = [s for s in telemetry.spans(trace_id) if s.name == "task export"]
    assert [span.kind for span in task_spans] == [SpanKind.CONSUMER]


async def test_temporary_failures_are_retried_with_backoff(
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
    connection: asyncpg.Connection,
    organization_id: UUID,
    telemetry: Telemetry,
) -> None:
    calls = Calls(failures_left=1)
    await enqueue(session_factory, queue, organization_id, "flaky")
    before = outcomes(telemetry)

    await drain(connection, registry_with(calls), session_factory)

    assert [report for report, _, _ in calls.seen] == ["flaky", "flaky"]
    assert await statuses(session_factory) == []
    assert delta(outcomes(telemetry), before) == {"retried": 1, "success": 1}


async def test_exhausted_and_rejected_jobs_are_held_not_deleted(
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
    connection: asyncpg.Connection,
    organization_id: UUID,
    telemetry: Telemetry,
) -> None:
    calls = Calls(failures_left=10)
    await enqueue(session_factory, queue, organization_id, "broken")
    await enqueue(session_factory, queue, organization_id, "reject")
    before = outcomes(telemetry)

    await drain(connection, registry_with(calls), session_factory)

    assert delta(outcomes(telemetry), before) == {"retried": 2, "failed": 2}

    assert [report for report, _, _ in calls.seen].count("broken") == 3
    assert [report for report, _, _ in calls.seen].count("reject") == 1
    assert sorted(await statuses(session_factory)) == [("failed", 0), ("failed", 2)]


async def test_cron_schedules_are_registered_and_run_in_a_unit_of_work(
    session_factory: Factory, connection: asyncpg.Connection, organization_id: UUID
) -> None:
    ran: list[str] = []
    registry = TaskRegistry()

    async def nightly() -> None:
        await OrderUseCase(OrderRepository()).create(uuid4(), organization_id, "cron")
        ran.append("nightly")

    registry.cron("nightly-cleanup", "0 3 * * *", nightly)
    worker = build_worker(connection, registry, session_factory)
    entries: dict[str, Any] = {
        str(key.entrypoint): executor.parameters.expression
        for key, executor in worker.sm.registry.items()
    }

    assert entries == {"nightly-cleanup": "0 3 * * *"}


async def test_malformed_task_is_held_without_entering_handler(
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    calls = Calls()
    with unit_of_work_scope(session_factory, user=User(id="u"), organization_id=organization_id):
        await execute(
            lambda: queue.enqueue(
                "export", {"wrongField": "invalid"}, organization_id=organization_id
            )
        )
    await drain(connection, registry_with(calls), session_factory)
    assert calls.seen == []
    assert await statuses(session_factory) == [("failed", 0)]


@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"])
async def test_out_of_range_task_timestamp_is_rejected_without_handler(
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
    connection: asyncpg.Connection,
    organization_id: UUID,
    caplog: pytest.LogCaptureFixture,
    timestamp: str,
) -> None:
    calls: list[TimestampData] = []
    registry = TaskRegistry()

    async def handle(_: TaskEnvelope, data: TimestampData) -> None:
        calls.append(data)

    registry.task("timestamp", TimestampData, handle)
    with unit_of_work_scope(session_factory, user=User(id="u"), organization_id=organization_id):
        await execute(
            lambda: queue.enqueue(
                "timestamp", {"payloadTimestamp": timestamp}, organization_id=organization_id
            )
        )
    await drain(connection, registry, session_factory)
    assert calls == []
    assert await statuses(session_factory) == [("failed", 0)]
    assert any(
        record.exc_info and isinstance(record.exc_info[1], TaskRejectedError)
        for record in caplog.records
    )


async def test_delayed_task_waits_until_execute_after(
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    registry = TaskRegistry()
    elapsed: list[float] = []
    started = time.monotonic()

    async def export(_: TaskEnvelope, __: ExportData) -> None:
        elapsed.append(time.monotonic() - started)

    registry.task("export", ExportData, export)
    with unit_of_work_scope(session_factory, user=User(id="u"), organization_id=organization_id):
        await execute(
            lambda: queue.enqueue(
                "export",
                {"report": "delayed"},
                organization_id=organization_id,
                delay=timedelta(seconds=0.5),
            )
        )
    worker = build_worker(connection, registry, session_factory)
    async with asyncio.timeout(5):
        await worker.run(mode=QueueExecutionMode.drain, dequeue_timeout=timedelta(seconds=0.05))
    assert len(elapsed) == 1
    assert elapsed[0] >= 0.5
    assert await statuses(session_factory) == []


async def test_retry_backoff_is_persisted_and_increases_between_real_attempts(
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    registry = TaskRegistry()
    attempts: list[float] = []

    async def export(_: TaskEnvelope, __: ExportData) -> None:
        attempts.append(time.monotonic())
        if len(attempts) < 3:
            raise RuntimeError("retry with delay")

    registry.task("export", ExportData, export)
    await enqueue(session_factory, queue, organization_id, "backoff")
    worker = build_worker(
        connection,
        registry,
        session_factory,
        retry=RetryPolicy(
            max_retries=2,
            base_delay=timedelta(seconds=0.1),
        ),
    )
    async with asyncio.timeout(5):
        await worker.run(mode=QueueExecutionMode.drain, dequeue_timeout=timedelta(seconds=0.02))
    assert len(attempts) == 3
    assert attempts[1] - attempts[0] >= 0.1
    assert attempts[2] - attempts[1] >= 0.2
    assert await statuses(session_factory) == []


async def test_two_complete_workers_claim_one_cron_occurrence_and_run_organization_jobs(
    database_url: str,
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
) -> None:
    connections = [
        await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://"))
        for _ in range(2)
    ]
    organizations = [uuid4(), uuid4()]
    cron_calls: list[tuple[str, UUID | None]] = []
    job_calls: list[tuple[str, UUID | None]] = []
    registry = TaskRegistry()
    workers: list[PgQueuer] = []

    async def nightly() -> None:
        cron_calls.append((current_user().id, current_organization_id()))
        for organization_id in organizations:
            await queue.enqueue("export", {"report": "nightly"}, organization_id=organization_id)

    async def export(_: TaskEnvelope, __: ExportData) -> None:
        job_calls.append((current_user().id, current_organization_id()))
        if len(job_calls) == 2:
            for worker in workers:
                worker.shutdown.set()

    registry.cron("nightly-once", "0 3 * * *", nightly)
    registry.task("export", ExportData, export)
    workers.extend(
        build_worker(connection, registry, session_factory) for connection in connections
    )
    try:
        key = next(iter(workers[0].sm.registry))
        await workers[0].sm.queries.insert_schedule({key: timedelta(seconds=-1)})
        async with asyncio.timeout(10):
            await asyncio.gather(
                *(worker.run(dequeue_timeout=timedelta(seconds=0.05)) for worker in workers)
            )
        assert cron_calls == [("schedule:nightly-once", None)]
        assert set(job_calls) == {
            ("task:export", organization_id) for organization_id in organizations
        }
        assert len(job_calls) == 2
        assert await statuses(session_factory) == []
    finally:
        for worker in workers:
            worker.shutdown.set()
        for connection in connections:
            await connection.close()


async def test_failed_cron_rolls_back_business_and_enqueue_then_drains_cleanly(
    connection: asyncpg.Connection,
    session_factory: Factory,
    queue: PgQueuerTaskQueue,
    organization_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = TaskRegistry()
    calls: list[UUID | None] = []

    async def nightly() -> None:
        calls.append(current_organization_id())
        with system_context("exercise schedule transaction rollback"):
            await OrderUseCase(OrderRepository()).create(uuid4(), organization_id, "cron-rollback")
        await queue.enqueue("export", {"report": "rolled-back"}, organization_id=organization_id)
        worker.shutdown.set()
        raise RuntimeError("cron failed after enqueue")

    registry.cron("nightly-failure", "0 3 * * *", nightly)
    registry.task("export", ExportData, registry_with(Calls()).tasks["export"].handler)
    worker = build_worker(connection, registry, session_factory)
    key = next(iter(worker.sm.registry))
    await worker.sm.queries.insert_schedule({key: timedelta(seconds=-1)})
    async with asyncio.timeout(10):
        await worker.run(dequeue_timeout=timedelta(seconds=0.05))
    assert calls == [None]
    assert await statuses(session_factory) == []
    async with session_factory() as session:
        assert (
            await session.execute(text(f"SELECT count(*) FROM {OrderModel.__tablename__}"))
        ).scalar_one() == 0
    assert "cron failed after enqueue" in caplog.text
