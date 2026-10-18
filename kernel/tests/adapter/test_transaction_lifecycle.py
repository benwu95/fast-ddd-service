import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd.context import User
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.controller import execute
from fast_ddd_adapter.infrastructure import configure
from fast_ddd_adapter.orm import DomainEventModel
from fast_ddd_adapter.session import SessionProvider
from fast_ddd_adapter.testing import unit_of_work_scope
from tests.adapter.models import Order, OrderModel, OrderRepository, OrderVoided, Status


async def test_outermost_property_tracks_nested_scope_and_exit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = SessionProvider(session_factory)
    assert not provider.is_outermost
    async with provider:
        assert provider.is_outermost
        async with provider:
            assert not provider.is_outermost
        assert provider.is_outermost
    assert not provider.is_outermost


@pytest.mark.parametrize("new", [True, False])
@pytest.mark.parametrize("nested", [True, False])
async def test_rolled_back_save_restores_lifecycle_and_original_events(
    session_factory: async_sessionmaker[AsyncSession],
    doer: User,
    organization_id: UUID,
    new: bool,
    nested: bool,
) -> None:
    configure(session_factory=session_factory, event_bus=EventBus())
    with unit_of_work_scope(
        session_factory, user=doer, organization_id=organization_id
    ) as provider:
        repo = OrderRepository()
        order = Order.create(id=uuid4(), organization_id=organization_id, code=str(uuid4()))
        if not new:
            await execute(lambda: repo.save(order))
            order.void("keep business change")
        original = (order.version, order.updated_at, order.domain_events)

        async def fail() -> None:
            await repo.save(order)
            raise RuntimeError("abort")

        if nested:
            async with provider:
                with pytest.raises(RuntimeError, match="abort"):
                    await execute(fail)
                assert (order.version, order.updated_at, order.domain_events) == original
                await execute(lambda: repo.save(order))
        else:
            with pytest.raises(RuntimeError, match="abort"):
                await execute(fail)
            assert (order.version, order.updated_at, order.domain_events) == original
            await execute(lambda: repo.save(order))
        assert order.domain_events == ()
        if not new:
            assert order.status is Status.VOIDED
    async with session_factory() as session:
        assert await session.get(OrderModel, order.id) is not None
        rows = (await session.scalars(select(DomainEventModel))).all()
    assert {row.event_id for row in rows}.issuperset(e.event_id for e in original[2])
    assert len(rows) == (1 if new else 2)


async def test_nested_journal_preserves_outer_save_and_event_order(
    session_factory: async_sessionmaker[AsyncSession],
    doer: User,
    organization_id: UUID,
) -> None:
    configure(session_factory=session_factory, event_bus=EventBus())
    with unit_of_work_scope(
        session_factory, user=doer, organization_id=organization_id
    ) as provider:
        order = Order.create(id=uuid4(), organization_id=organization_id, code="journal")
        repo = OrderRepository()
        created = order.domain_events[0]

        async def outer() -> None:
            async with provider:
                await execute(lambda: repo.save(order))
                order.void("first")
                first = order.domain_events[0]
                later_events: list[OrderVoided] = []

                async def inner() -> None:
                    async with provider.savepoint():
                        await repo.save(order)
                        order.add_event(OrderVoided(doer=doer, reason="second"))
                        await repo.save(order)
                        order.add_event(OrderVoided(doer=doer, reason="third"))
                        third = order.domain_events[0]
                        assert isinstance(third, OrderVoided)
                        later_events.append(third)
                        raise RuntimeError("inner")

                with pytest.raises(RuntimeError, match="inner"):
                    await inner()
                assert order.version == 1
                assert [e.reason for e in order.domain_events if isinstance(e, OrderVoided)] == [
                    "first",
                    "second",
                    "third",
                ]
                assert order.domain_events[0] is first
                assert order.domain_events[-1] is later_events[0]
                raise RuntimeError("outer")

        with pytest.raises(RuntimeError, match="outer"):
            await outer()
        assert order.version == 0
        assert order.domain_events[0] is created
        assert len(order.domain_events) == 4
        await execute(lambda: repo.save(order))
        order.code = "committed"

        async def later() -> None:
            async with provider:
                await repo.save(order)
                raise RuntimeError("later")

        with pytest.raises(RuntimeError, match="later"):
            await later()
        assert order.version == 1
        assert order.domain_events == ()


@pytest.mark.parametrize("rollback", [True, False])
async def test_completed_transaction_hooks_can_execute_new_transactions(
    session_factory: async_sessionmaker[AsyncSession],
    doer: User,
    organization_id: UUID,
    rollback: bool,
) -> None:
    configure(session_factory=session_factory, event_bus=EventBus())
    published: list[str] = []
    called: list[str] = []
    with unit_of_work_scope(
        session_factory, user=doer, organization_id=organization_id
    ) as provider:

        async def publish() -> None:
            published.append("old")

        async def reenter() -> None:
            assert not provider.is_active

            async def command() -> None:
                await provider.session.execute(text("SELECT 1"))

                async def fresh() -> None:
                    published.append("fresh")

                provider.after_commit(fresh)

            await execute(command)
            called.append("first")

        async def second() -> None:
            called.append("second")

        async def transaction() -> None:
            async with provider:
                await provider.session.execute(text("SELECT 1"))
                if rollback:
                    provider.after_commit(publish)
                    provider.on_rollback(reenter)
                    provider.on_rollback(second)
                    raise RuntimeError("abort")
                provider.after_commit(reenter)
                provider.after_commit(second)

        if rollback:
            with pytest.raises(RuntimeError, match="abort"):
                await transaction()
        else:
            await transaction()
    assert published == ["fresh"]
    assert called == ["first", "second"]


async def test_commit_failure_rolls_back_lifecycle_and_runs_failure_hooks(
    session_factory: async_sessionmaker[AsyncSession],
    doer: User,
    organization_id: UUID,
) -> None:
    configure(session_factory=session_factory, event_bus=EventBus())
    called: list[str] = []
    with unit_of_work_scope(
        session_factory, user=doer, organization_id=organization_id
    ) as provider:
        order = Order.create(id=uuid4(), organization_id=organization_id, code="deferred")
        original = order.domain_events

        async def failure() -> None:
            async def command() -> None:
                await provider.session.execute(text("SELECT 1"))

            await execute(command)
            called.append("rollback")

        async def success() -> None:
            called.append("commit")

        async def transaction() -> None:
            async with provider:
                await provider.session.execute(
                    text("CREATE TEMP TABLE lifecycle_parent (id INT PRIMARY KEY)")
                )
                await provider.session.execute(
                    text(
                        "CREATE TEMP TABLE lifecycle_child (id INT REFERENCES lifecycle_parent(id) "
                        "DEFERRABLE INITIALLY DEFERRED)"
                    )
                )
                await provider.session.execute(text("INSERT INTO lifecycle_child VALUES (1)"))
                await OrderRepository().save(order)
                provider.on_rollback(failure)
                provider.after_commit(success)

        with pytest.raises(IntegrityError):
            await transaction()
        assert called == ["rollback"]
        assert order.version == 0
        assert order.domain_events == original
        await execute(lambda: OrderRepository().save(order))
    async with session_factory() as session:
        assert await session.get(OrderModel, order.id) is not None


@pytest.mark.parametrize("cleanup", ["rollback", "close"])
async def test_cleanup_failure_preserves_transaction_failure_and_detaches_state(
    cleanup: str,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    failure = RuntimeError("commit failed")
    session.commit.side_effect = failure
    getattr(session, cleanup).side_effect = RuntimeError("cleanup failed")
    factory = Mock(spec=async_sessionmaker)
    factory.return_value = session
    provider = SessionProvider(factory)
    called: list[str] = []

    async def rollback() -> None:
        called.append("rollback")

    with pytest.raises(RuntimeError, match="commit failed") as raised:
        async with provider:
            provider.on_rollback(rollback)
    assert raised.value is failure
    assert not provider.is_active
    session.close.assert_awaited_once()
    session.rollback.assert_awaited_once()
    assert called == ["rollback"]
    with pytest.raises(RuntimeError, match="no active transaction"):
        _ = provider.session


@pytest.mark.parametrize("operation", ["commit", "rollback", "close"])
async def test_cancelled_transaction_cleanup_closes_and_resets(operation: str) -> None:
    session = AsyncMock(spec=AsyncSession)
    cancellation = asyncio.CancelledError()
    getattr(session, operation).side_effect = cancellation
    factory = Mock(spec=async_sessionmaker)
    factory.return_value = session
    provider = SessionProvider(factory)
    called: list[str] = []

    async def failure_hook() -> None:
        called.append("rollback")

    async def business_failure() -> None:
        async with provider:
            provider.on_rollback(failure_hook)
            raise RuntimeError("business failure")

    if operation == "rollback":
        with pytest.raises(RuntimeError, match="business failure"):
            await business_failure()
    else:
        with pytest.raises(asyncio.CancelledError) as raised:
            async with provider:
                provider.on_rollback(failure_hook)
        assert raised.value is cancellation
    assert called == ([] if operation == "close" else ["rollback"])
    session.close.assert_awaited_once()
    assert not provider.is_active
    with pytest.raises(RuntimeError, match="no active transaction"):
        _ = provider.session


async def test_savepoint_rollback_hooks_wait_for_outer_transaction_rollback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    called: list[str] = []
    provider = SessionProvider(session_factory)

    async def failure_hook() -> None:
        called.append("outer rollback")

    async def savepoint() -> None:
        async with provider.savepoint():
            provider.on_rollback(failure_hook)
            raise RuntimeError("savepoint")

    async def outer() -> None:
        async with provider:
            with pytest.raises(RuntimeError, match="savepoint"):
                await savepoint()
            assert called == []
            raise RuntimeError("outer")

    with pytest.raises(RuntimeError, match="outer"):
        await outer()
    assert called == ["outer rollback"]
