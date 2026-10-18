import asyncio
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fast_ddd.context import User, unit_of_work_context
from fast_ddd_adapter.infrastructure import system_context
from fast_ddd_adapter.orm import DomainEventModel
from fast_ddd_adapter.repository import RepositoryBase, TenantContextMissingError, TenantScope
from fast_ddd_adapter.session import (
    AlreadySavedInThisCommandError,
    SessionProvider,
    session_provider_scope,
)
from fast_ddd_adapter.testing import count_statements
from tests.adapter.models import (
    ArchivedOrderRepository,
    Line,
    Order,
    OrderArchiveModel,
    OrderModel,
    OrderRepository,
    Status,
)


class Boom(Exception):
    pass


class RootOnlyRepository(RepositoryBase[UUID, Order, OrderModel]):
    aggregate_class = Order
    model_class = OrderModel
    tenant_scope: ClassVar[TenantScope] = "organization"

    def model_to_entity(self, model: OrderModel) -> Order:
        return Order(
            id=model.id,
            organization_id=model.organization_id,
            code=model.code,
            lines=[],
            status=Status(model.status),
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def entity_to_model(self, entity: Order, model: OrderModel | None) -> OrderModel:
        if model is None:
            model = OrderModel(id=entity.id)
        model.organization_id = entity.organization_id
        model.version = entity.version
        model.created_at = entity.created_at
        model.updated_at = entity.updated_at
        model.code = entity.code
        model.status = entity.status.value
        return model


async def test_root_only_repository_uses_default_load_and_child_hooks(
    session_factory: async_sessionmaker[AsyncSession], doer: User, organization_id: UUID
) -> None:
    repo = RootOnlyRepository()
    with unit_of_work_context(user=doer, organization_id=organization_id):
        provider = SessionProvider(session_factory)
        with session_provider_scope(provider):
            async with provider:
                order = Order.create(id=uuid4(), organization_id=organization_id, code="root")
                await repo.save(order)
            async with provider:
                loaded = await repo.load(order.id, lock=True)
                assert (loaded.code, loaded.lines, loaded.version) == ("root", [], 1)
                assert repo.load_options() == ()
                assert tuple(repo.child_models(OrderModel())) == ()
                await repo.save(loaded)
                assert loaded.version == 1
                loaded.void("root-only update")
                await repo.save(loaded)
                assert loaded.version == 2
            async with provider:
                reloaded = await repo.load(order.id, lock=False)
                assert reloaded.status is Status.VOIDED
                assert reloaded.version == 2


async def _create(
    factory: async_sessionmaker[AsyncSession], doer: User, org: UUID, *, lines: int = 0
) -> Order:
    with unit_of_work_context(user=doer, organization_id=org):
        provider = SessionProvider(factory)
        with session_provider_scope(provider):
            async with provider:
                order = Order.create(id=uuid4(), organization_id=org, code=str(uuid4())[:8])
                order.lines = [Line(uuid4(), 1) for _ in range(lines)]
                await OrderRepository().save(order)
    return order


async def _load(
    factory: async_sessionmaker[AsyncSession], doer: User, org: UUID | None, order_id: UUID
) -> Order | None:
    with unit_of_work_context(user=doer, organization_id=org):
        provider = SessionProvider(factory)
        with session_provider_scope(provider):
            async with provider:
                return (await OrderRepository().load_many([order_id], lock=False)).get(order_id)


async def test_version_increments_only_on_real_changes(
    session_factory: async_sessionmaker[AsyncSession], doer: User, organization_id: UUID
) -> None:
    order = await _create(session_factory, doer, organization_id, lines=2)
    assert order.version == 1

    async def update(mutate: str) -> Order:
        with unit_of_work_context(user=doer, organization_id=organization_id):
            provider = SessionProvider(session_factory)
            with session_provider_scope(provider):
                async with provider:
                    repo = OrderRepository()
                    loaded = await repo.load(order.id, lock=True)
                    if mutate == "child":
                        loaded.change_line(loaded.lines[0].line_id, 7)
                    elif mutate == "root":
                        loaded.void("typo")
                    await repo.save(loaded)
                    return loaded

    unchanged = await update("none")
    assert unchanged.version == 1
    assert unchanged.created_at == order.created_at
    assert unchanged.updated_at == order.updated_at
    assert (await update("child")).version == 2
    voided = await update("root")
    assert voided.version == 3
    assert voided.updated_at >= voided.created_at


async def test_domain_events_are_persisted_with_source_aggregate(
    session_factory: async_sessionmaker[AsyncSession], doer: User, organization_id: UUID
) -> None:
    order = await _create(session_factory, doer, organization_id)

    async with session_factory() as session:
        row = (await session.execute(select(DomainEventModel))).scalar_one()

    assert row.name == "OrderCreated"
    assert row.aggregate_type == "order"
    assert row.aggregate_id == order.id
    assert row.organization_id == organization_id
    assert row.body == {"code": order.code}
    assert row.doer == {"id": "tester", "name": "Tester"}


async def test_tenant_filter_hides_other_organizations(
    session_factory: async_sessionmaker[AsyncSession], doer: User, organization_id: UUID
) -> None:
    order = await _create(session_factory, doer, organization_id)

    assert await _load(session_factory, doer, uuid4(), order.id) is None
    assert await _load(session_factory, doer, organization_id, order.id) is not None
    with pytest.raises(TenantContextMissingError):
        await _load(session_factory, doer, None, order.id)

    with unit_of_work_context(user=doer, organization_id=None):
        provider = SessionProvider(session_factory)
        with session_provider_scope(provider), system_context("test"):
            async with provider:
                found = await OrderRepository().load_many([order.id], lock=False)
    assert order.id in found


def test_repository_must_declare_tenant_scope() -> None:
    with pytest.raises(TypeError, match="tenant_scope"):

        class Undeclared(OrderRepository):  # pyright: ignore[reportUnusedClass]
            pass


async def test_locked_load_refreshes_identity_map(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    doer: User,
    organization_id: UUID,
) -> None:
    order = await _create(session_factory, doer, organization_id)
    with unit_of_work_context(user=doer, organization_id=organization_id):
        provider = SessionProvider(session_factory)
        with session_provider_scope(provider):
            async with provider:
                repo = OrderRepository()
                await repo.load(order.id, lock=False)
                async with engine.begin() as other:
                    await other.execute(
                        text(
                            "UPDATE kernel_test_order SET status = 'voided', version = 7 "
                            "WHERE id = :id"
                        ),
                        {"id": order.id},
                    )
                locked = await repo.load(order.id, lock=True)

    assert locked.status.value == "voided"
    assert locked.version == 7


async def test_only_outermost_scope_commits_and_exceptions_roll_back(
    session_factory: async_sessionmaker[AsyncSession], doer: User, organization_id: UUID
) -> None:
    calls: list[str] = []

    async def after() -> None:
        calls.append("after-commit")

    async def rolled_back() -> None:
        calls.append("on-rollback")

    async def nested_failure(provider: SessionProvider) -> None:
        async with provider:
            raise Boom

    async def unit_of_work(provider: SessionProvider) -> None:
        async with provider:
            provider.on_rollback(rolled_back)
            provider.after_commit(after)
            await OrderRepository().save(
                Order.create(id=uuid4(), organization_id=organization_id, code="x1")
            )
            with pytest.raises(Boom):
                await nested_failure(provider)
            assert provider.is_active
            raise Boom

    provider = SessionProvider(session_factory)
    with (
        unit_of_work_context(user=doer, organization_id=organization_id),
        session_provider_scope(provider),
        pytest.raises(Boom),
    ):
        await unit_of_work(provider)

    assert calls == ["on-rollback"]
    async with session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(OrderModel))).scalar() == 0


async def test_savepoint_rollback_discards_hooks_saves_and_events(
    session_factory: async_sessionmaker[AsyncSession], doer: User, organization_id: UUID
) -> None:
    calls: list[str] = []

    async def hook(name: str) -> None:
        calls.append(name)

    with unit_of_work_context(user=doer, organization_id=organization_id):
        provider = SessionProvider(session_factory)
        with session_provider_scope(provider):
            async with provider:
                provider.after_commit(lambda: hook("kept"))
                mark = provider.mark()

                async def failing_savepoint() -> None:
                    async with provider.savepoint():
                        provider.after_commit(lambda: hook("discarded"))
                        await OrderRepository().save(
                            Order.create(id=uuid4(), organization_id=organization_id, code="x2")
                        )
                        raise Boom

                with pytest.raises(Boom):
                    await failing_savepoint()
                assert provider.saved_since(mark) == []
                assert provider.take_pending_events(mark) == []

    assert calls == ["kept"]


async def test_after_commit_hook_failure_is_logged_not_raised(
    session_factory: async_sessionmaker[AsyncSession],
    doer: User,
    organization_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    async def failing() -> None:
        raise Boom

    async def ok() -> None:
        calls.append("ok")

    with unit_of_work_context(user=doer, organization_id=organization_id):
        provider = SessionProvider(session_factory)
        with session_provider_scope(provider):
            async with provider:
                provider.after_commit(failing)
                provider.after_commit(ok)

    assert calls == ["ok"]
    assert any("after-commit hook failed" in r.message and r.exc_info for r in caplog.records)


async def test_protected_aggregate_cannot_be_saved_again(
    session_factory: async_sessionmaker[AsyncSession], doer: User, organization_id: UUID
) -> None:
    async def save_twice(provider: SessionProvider) -> None:
        async with provider:
            order = Order.create(id=uuid4(), organization_id=organization_id, code="x3")
            mark = provider.mark()
            await OrderRepository().save(order)
            with provider.protect(provider.saved_since(mark)):
                order.void("again")
                await OrderRepository().save(order)

    provider = SessionProvider(session_factory)
    with (
        unit_of_work_context(user=doer, organization_id=organization_id),
        session_provider_scope(provider),
        pytest.raises(AlreadySavedInThisCommandError),
    ):
        await save_twice(provider)


async def test_archive_snapshot_only_when_enabled(
    session_factory: async_sessionmaker[AsyncSession], doer: User, organization_id: UUID
) -> None:
    order = await _create(session_factory, doer, organization_id)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OrderArchiveModel)) == 0
    with unit_of_work_context(user=doer, organization_id=organization_id):
        provider = SessionProvider(session_factory)
        with session_provider_scope(provider):
            async with provider:
                repo: RepositoryBase[UUID, Order, OrderModel] = ArchivedOrderRepository()
                loaded = await repo.load(order.id, lock=True)
                loaded.void("archived")
                await repo.save(loaded)

    async with session_factory() as session:
        snapshot = (await session.execute(select(OrderArchiveModel))).scalar_one()
    assert snapshot.id == order.id
    assert snapshot.status == "voided"
    assert snapshot.version == 2
    assert snapshot.event_name == "OrderVoided"
    assert snapshot.organization_id == organization_id
    async with session_factory() as session:
        event = await session.get(DomainEventModel, snapshot.event_id)
    assert event is not None
    assert event.aggregate_id == order.id
    assert event.organization_id == organization_id


async def test_save_many_uses_constant_round_trips(
    session_factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    doer: User,
    organization_id: UUID,
) -> None:
    async def create(n: int) -> int:
        with unit_of_work_context(user=doer, organization_id=organization_id):
            provider = SessionProvider(session_factory)
            with session_provider_scope(provider):
                async with provider:
                    orders = [
                        Order.create(
                            id=uuid4(), organization_id=organization_id, code=str(uuid4())[:8]
                        )
                        for _ in range(n)
                    ]
                    with count_statements(engine) as counter:
                        await OrderRepository().save_many(orders)
                    return counter.count

    assert await create(1) == await create(50)


async def test_concurrent_units_of_work_do_not_share_context(
    session_factory: async_sessionmaker[AsyncSession], organization_id: UUID
) -> None:
    async def create_as(user_id: str) -> str:
        user = User(id=user_id)
        with unit_of_work_context(user=user, organization_id=organization_id):
            provider = SessionProvider(session_factory)
            with session_provider_scope(provider):
                async with provider:
                    order = Order.create(id=uuid4(), organization_id=organization_id, code=user_id)
                    await asyncio.sleep(0)
                    await OrderRepository().save(order)
        return user_id

    await asyncio.gather(*(create_as(f"u{i}") for i in range(5)))

    async with session_factory() as session:
        rows = (await session.execute(select(DomainEventModel))).scalars().all()
    assert sorted((r.doer["id"], r.body["code"]) for r in rows) == [
        (f"u{i}", f"u{i}") for i in range(5)
    ]
