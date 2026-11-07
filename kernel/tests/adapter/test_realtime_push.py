import asyncio
import gc
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd.context import User
from fast_ddd_adapter import realtime
from fast_ddd_adapter.infrastructure import NotConfiguredError
from fast_ddd_adapter.realtime import (
    KernelAioPikaManager,
    RealtimeEmitter,
    RealtimePushError,
    configure_realtime,
    create_realtime_emitter,
    push_after_commit,
    realtime_channel,
    resource_room,
    user_room,
)
from fast_ddd_adapter.session import SessionProvider
from fast_ddd_adapter.testing import unit_of_work_scope
from fast_ddd_port.testing import TokenFactory
from tests.realtime_support import (
    CHANNEL,
    JWT_SETTINGS,
    SERVICE,
    Client,
    RunningApp,
    amqp_tasks,
    connected,
    running_app,
    settle,
    wait_for_listener,
    wait_until,
)

EVENT = "order.updated"
DOER = User(id="tester", name=None)


@pytest.fixture
async def emitter(amqp_url: str) -> AsyncGenerator[RealtimeEmitter]:
    emitter = create_realtime_emitter(amqp_url, service=SERVICE)
    previous = realtime._emitter  # pyright: ignore[reportPrivateUsage]
    configure_realtime(emitter)
    yield emitter
    realtime._emitter = previous  # pyright: ignore[reportPrivateUsage]
    await emitter.close()


@pytest.fixture
async def app(amqp_url: str) -> AsyncGenerator[tuple[RunningApp, TokenFactory]]:
    tokens = TokenFactory(JWT_SETTINGS)
    async with running_app(tokens, amqp_url) as running:
        yield running, tokens


@pytest.fixture
async def client(
    app: tuple[RunningApp, TokenFactory], emitter: RealtimeEmitter, organization_id: UUID
) -> AsyncGenerator[Client]:
    running, tokens = app
    token = tokens.token(organization_id=organization_id, user_id="watcher")
    async with connected(running.url, {"token": token}, events=[EVENT]) as client:
        await wait_for_listener(emitter, client, "watcher")
        yield client


async def test_push_is_sent_only_after_the_outermost_commit(
    session_factory: async_sessionmaker[AsyncSession], organization_id: UUID, client: Client
) -> None:
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id) as uow:
        async with uow:
            push_after_commit(EVENT, 2, {"orderId": "o-1", "lineItems": [1]}, organization=True)
            await settle()
            assert client.events(EVENT) == []
    await wait_until(lambda: len(client.events(EVENT)) == 1)
    assert client.events(EVENT) == [
        {"eventName": EVENT, "eventVersion": 2, "data": {"orderId": "o-1", "lineItems": [1]}}
    ]


async def test_rollback_discards_the_push(
    session_factory: async_sessionmaker[AsyncSession], organization_id: UUID, client: Client
) -> None:
    async def failing(uow: SessionProvider) -> None:
        async with uow:
            push_after_commit(EVENT, 1, {"n": 1}, users=["watcher"])
            raise RuntimeError("business failure")

    with (
        unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id) as uow,
        pytest.raises(RuntimeError, match="business failure"),
    ):
        await failing(uow)
    await settle()
    assert client.events(EVENT) == []


async def test_savepoint_rollback_discards_only_its_own_push(
    session_factory: async_sessionmaker[AsyncSession], organization_id: UUID, client: Client
) -> None:
    async def nested(uow: SessionProvider) -> None:
        async with uow.savepoint():
            push_after_commit(EVENT, 1, {"n": "nested"}, organization=True)
            raise RuntimeError("nested")

    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id) as uow:
        async with uow:
            with pytest.raises(RuntimeError, match="nested"):
                await nested(uow)
            push_after_commit(EVENT, 1, {"n": "outer"}, organization=True)
    await wait_until(lambda: len(client.events(EVENT)) == 1)
    await settle()
    assert [event["data"] for event in client.events(EVENT)] == [{"n": "outer"}]


async def test_push_sends_the_registered_snapshot_once_per_client(
    session_factory: async_sessionmaker[AsyncSession], organization_id: UUID, client: Client
) -> None:
    data: dict[str, Any] = {"items": [1]}
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id) as uow:
        async with uow:
            push_after_commit(EVENT, 1, data, organization=True, users=["watcher", "watcher"])
            data["items"].append(2)
    await wait_until(lambda: len(client.events(EVENT)) == 1)
    await settle()
    assert client.events(EVENT)[0]["data"] == {"items": [1]}
    assert len(client.events(EVENT)) == 1


async def test_resource_push_targets_the_organization_scoped_room(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
    app: tuple[RunningApp, TokenFactory],
    emitter: RealtimeEmitter,
) -> None:
    running, tokens = app
    order_id = uuid4()
    token = tokens.token(organization_id=organization_id, user_id="r", permissions=["order:read"])
    async with connected(running.url, {"token": token}, events=[EVENT]) as client:
        await wait_for_listener(emitter, client, "r")
        assert (await client.join("order", order_id))["status"] == "ok"
        other = uuid4()
        with unit_of_work_scope(session_factory, user=DOER, organization_id=other) as uow:
            async with uow:
                push_after_commit(EVENT, 1, {"org": "other"}, resources=[("order", order_id)])
        with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id) as uow:
            async with uow:
                push_after_commit(EVENT, 1, {"org": "own"}, resources=[("order", order_id)])
        await wait_until(lambda: len(client.events(EVENT)) == 1)
        await settle()
    assert [event["data"] for event in client.events(EVENT)] == [{"org": "own"}]


@pytest.mark.parametrize(
    ("organization_id", "targets", "data", "message"),
    [
        (uuid4(), {}, {}, "at least one room"),
        (None, {"organization": True}, {}, "need an organization"),
        (None, {"resources": [("order", uuid4())]}, {}, "need an organization"),
        (uuid4(), {"users": "alice"}, {}, "not one string"),
        (uuid4(), {"users": ["u"]}, {"id": uuid4()}, "must be JSON"),
        (uuid4(), {"users": ["u"]}, {"ratio": float("nan")}, "must be JSON"),
    ],
)
@pytest.mark.usefixtures("emitter")
async def test_invalid_push_is_rejected_when_registered(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID | None,
    targets: dict[str, Any],
    data: dict[str, Any],
    message: str,
) -> None:
    with unit_of_work_scope(session_factory, user=DOER, organization_id=organization_id) as uow:
        async with uow:
            with pytest.raises(RealtimePushError, match=message):
                push_after_commit(EVENT, 1, data, **targets)
            assert uow.mark().after_commit == 0


@pytest.mark.usefixtures("emitter")
async def test_circular_data_is_rejected(session_factory: async_sessionmaker[AsyncSession]) -> None:
    looped: dict[str, Any] = {}
    looped["self"] = looped
    with unit_of_work_scope(session_factory, user=DOER, organization_id=uuid4()) as uow:
        async with uow:
            with pytest.raises(RealtimePushError, match="must be JSON"):
                push_after_commit(EVENT, 1, looped, users=["u"])


def test_room_names_validate_their_parts() -> None:
    organization_id, order_id = uuid4(), uuid4()
    assert resource_room(organization_id, "sales_order", order_id) == (
        f"org:{organization_id}:sales_order:{order_id}"
    )
    assert user_room("u-1") == "user:u-1"
    for bad in ("Order", "order:x", "1order", ""):
        with pytest.raises(ValueError, match="snake_case"):
            resource_room(organization_id, bad, order_id)
    with pytest.raises(ValueError, match="empty"):
        user_room(" ")


async def test_push_without_configured_emitter_fails(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(realtime, "_emitter", None)
    with unit_of_work_scope(session_factory, user=DOER, organization_id=uuid4()) as uow:
        async with uow:
            with pytest.raises(NotConfiguredError, match="configure_realtime"):
                push_after_commit(EVENT, 1, {}, users=["u"])


class SlowFirstConnect(KernelAioPikaManager):
    connects = 0

    async def _connect(self) -> Any:
        self.connects += 1
        if self.connects == 1:
            await asyncio.sleep(5)
        return await super()._connect()


async def test_interrupted_first_connect_does_not_break_later_pushes(
    amqp_url: str, client: Client
) -> None:
    slow = RealtimeEmitter(
        SlowFirstConnect(amqp_url, channel=CHANNEL, write_only=True), emit_timeout_seconds=0.2
    )
    try:
        with pytest.raises(TimeoutError):
            await slow.emit(EVENT, {"n": 1}, to=[user_room("watcher")])
        await slow.emit(EVENT, {"n": 2}, to=[user_room("watcher")])
        await wait_until(lambda: client.events(EVENT) == [{"n": 2}])
    finally:
        await slow.close()


class SpuriouslyCancelled(KernelAioPikaManager):
    async def emit(self, *_: Any, **__: Any) -> None:
        raise asyncio.CancelledError


class Stalled(KernelAioPikaManager):
    async def emit(self, *_: Any, **__: Any) -> None:
        await asyncio.sleep(5)


@pytest.mark.parametrize(
    ("manager", "logged"),
    [(SpuriouslyCancelled, "interrupted by a reset"), (Stalled, "TimeoutError")],
)
async def test_failed_push_is_logged_and_later_hooks_still_run(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    manager: type[KernelAioPikaManager],
    logged: str,
) -> None:
    failing = RealtimeEmitter(
        manager("amqp://unused/", channel=CHANNEL, write_only=True), emit_timeout_seconds=0.2
    )
    monkeypatch.setattr(realtime, "_emitter", failing)
    ran: list[str] = []

    async def later() -> None:
        ran.append("later")

    caplog.set_level(logging.ERROR, logger="fast_ddd_adapter.session")
    with unit_of_work_scope(session_factory, user=DOER, organization_id=uuid4()) as uow:
        async with uow:
            push_after_commit(EVENT, 1, {}, users=["u"])
            uow.after_commit(later)
    assert ran == ["later"]
    assert "after-commit hook failed" in caplog.text
    assert logged in caplog.text


async def test_emit_refuses_an_empty_room_list(emitter: RealtimeEmitter) -> None:
    with pytest.raises(RealtimePushError, match="at least one room"):
        await emitter.emit(EVENT, {}, to=[])


@pytest.mark.parametrize("used", [False, True])
async def test_emitter_close_leaves_no_amqp_tasks(amqp_url: str, used: bool) -> None:
    before = amqp_tasks()
    emitter = create_realtime_emitter(amqp_url, service=SERVICE)
    if used:
        await emitter.emit(EVENT, {}, to=[user_room("nobody")])
    await emitter.close()
    await asyncio.sleep(0.1)
    gc.collect()
    assert amqp_tasks() - before == set()


async def test_timed_out_connect_leaves_no_reconnecting_connection() -> None:
    accepted: list[asyncio.StreamWriter] = []

    async def hang(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.append(writer)
        await asyncio.sleep(30)

    broker = await asyncio.start_server(hang, "127.0.0.1", 0)
    port = broker.sockets[0].getsockname()[1]
    before = amqp_tasks()
    emitter = create_realtime_emitter(
        f"amqp://guest:guest@127.0.0.1:{port}/",
        service=SERVICE,
        emit_timeout_seconds=0.2,
        connect_timeout_seconds=5,
    )
    try:
        with pytest.raises(TimeoutError):
            await emitter.emit(EVENT, {}, to=[user_room("nobody")])
        await emitter.close()
        await asyncio.sleep(0.2)
        assert amqp_tasks() - before == set()
    finally:
        for writer in accepted:
            writer.close()
        broker.close()
        await broker.wait_closed()


async def test_cancelled_publish_keeps_the_shared_connection(amqp_url: str, client: Client) -> None:
    manager = KernelAioPikaManager(amqp_url, channel=CHANNEL, write_only=True)
    shared = RealtimeEmitter(manager, emit_timeout_seconds=5)
    try:
        await shared.emit(EVENT, {"n": 1}, to=[user_room("watcher")])
        publisher = manager._publisher  # pyright: ignore[reportPrivateUsage]
        assert publisher is not None
        cancelled = asyncio.create_task(shared.emit(EVENT, {"n": 2}, to=[user_room("watcher")]))
        await asyncio.sleep(0)
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
        assert manager._publisher is publisher  # pyright: ignore[reportPrivateUsage]
        assert not publisher[0].is_closed
        await shared.emit(EVENT, {"n": 3}, to=[user_room("watcher")])
        await wait_until(lambda: {"n": 3} in client.events(EVENT))
    finally:
        await shared.close()


async def test_close_waits_for_a_publisher_connection_being_created(amqp_url: str) -> None:
    before = amqp_tasks()
    manager = KernelAioPikaManager(amqp_url, channel=CHANNEL, write_only=True)
    publishing = asyncio.create_task(manager.emit(EVENT, {}, namespace="/", to=["user:x"]))
    await asyncio.sleep(0.001)
    await manager.close()
    await asyncio.gather(publishing, return_exceptions=True)
    await asyncio.sleep(0.1)
    assert manager._publisher is None  # pyright: ignore[reportPrivateUsage]
    assert amqp_tasks() - before == set()
    with pytest.raises(RuntimeError, match="closed"):
        await manager.emit(EVENT, {}, namespace="/", to=["user:x"])


async def test_pushes_stay_inside_their_service(
    amqp_url: str, app: tuple[RunningApp, TokenFactory], emitter: RealtimeEmitter
) -> None:
    running, tokens = app
    token = tokens.token(organization_id=None, user_id="iris")
    other = create_realtime_emitter(amqp_url, service="another-service")
    try:
        async with connected(running.url, {"token": token}, events=[EVENT]) as client:
            await wait_for_listener(emitter, client, "iris")
            await other.emit(EVENT, {"from": "another-service"}, to=[user_room("iris")])
            await settle()
            assert client.events(EVENT) == []
    finally:
        await other.close()


def test_service_name_is_validated() -> None:
    assert realtime_channel("billing-api") == "fast_ddd.realtime.billing-api"
    for bad in ("", "Billing", "billing.api", "-billing"):
        with pytest.raises(ValueError, match="service name"):
            realtime_channel(bad)
