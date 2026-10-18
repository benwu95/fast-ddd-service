from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd.context import User, unit_of_work_context
from fast_ddd.errors import AggregateNotFound
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.controller import execute
from fast_ddd_adapter.infrastructure import configure, system_context
from fast_ddd_adapter.orm import DomainEventModel
from fast_ddd_adapter.repository import TenantContextMissingError
from fast_ddd_adapter.testing import unit_of_work_scope
from tests.adapter.models import ArchivedOrderRepository, Order, OrderArchiveModel, OrderRepository

type Factory = async_sessionmaker[AsyncSession]


async def _created(factory: Factory, doer: User, organization_id: UUID) -> Order:
    with unit_of_work_scope(factory, user=doer, organization_id=organization_id) as provider:
        async with provider:
            order = Order.create(id=uuid4(), organization_id=organization_id, code=str(uuid4()))
            await OrderRepository().save(order)
            return order


@pytest.mark.parametrize("existing", [False, True])
async def test_save_requires_tenant_context_even_when_aggregate_has_organization(
    session_factory: Factory, doer: User, organization_id: UUID, existing: bool
) -> None:
    order = await _created(session_factory, doer, organization_id)
    if not existing:
        with unit_of_work_context(user=doer, organization_id=organization_id):
            order = Order.create(id=uuid4(), organization_id=organization_id, code=str(uuid4()))
    with (
        unit_of_work_scope(session_factory, user=doer, organization_id=None) as provider,
        pytest.raises(TenantContextMissingError),
    ):
        async with provider:
            await OrderRepository().save(order)


@pytest.mark.parametrize("operation", ["load", "save"])
async def test_empty_repository_operations_still_require_tenant_context(
    session_factory: Factory, doer: User, operation: str
) -> None:
    with unit_of_work_scope(session_factory, user=doer, organization_id=None) as provider:
        async with provider:
            repository = OrderRepository()
            with pytest.raises(TenantContextMissingError):
                await (
                    repository.load_many([], lock=False)
                    if operation == "load"
                    else repository.save_many([])
                )


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("forged_organization", [False, True])
@pytest.mark.parametrize("delete", [False, True])
async def test_saving_other_tenant_aggregate_is_not_found(
    session_factory: Factory,
    doer: User,
    organization_id: UUID,
    cached: bool,
    forged_organization: bool,
    delete: bool,
) -> None:
    order = await _created(session_factory, doer, organization_id)
    other_organization = uuid4()
    with unit_of_work_scope(
        session_factory, user=doer, organization_id=other_organization
    ) as provider:
        async with provider:
            repository = OrderRepository()
            if cached:
                with system_context("load original tenant to test write authorization"):
                    order = await repository.load(order.id, lock=True)
            if forged_organization:
                order.organization_id = other_organization
            if delete:
                order.mark_deleted()
            else:
                order.code = "unauthorized"
            with pytest.raises(AggregateNotFound):
                await repository.save(order)
    with unit_of_work_scope(
        session_factory, user=doer, organization_id=organization_id
    ) as provider:
        async with provider:
            saved = await OrderRepository().load(order.id, lock=False)
            assert saved.code != "unauthorized"
            assert saved.organization_id == organization_id
            assert saved.version == 1


async def test_new_aggregate_cannot_target_other_tenant(
    session_factory: Factory, doer: User, organization_id: UUID
) -> None:
    with unit_of_work_scope(
        session_factory, user=doer, organization_id=organization_id
    ) as provider:
        async with provider:
            order = Order.create(id=uuid4(), organization_id=uuid4(), code=str(uuid4()))
            with pytest.raises(AggregateNotFound):
                await OrderRepository().save(order)


async def test_system_write_preserves_each_organization_and_logs_exemption(
    session_factory: Factory, doer: User, caplog: pytest.LogCaptureFixture
) -> None:
    organizations = [uuid4(), uuid4()]
    with unit_of_work_scope(session_factory, user=doer, organization_id=None) as provider:
        async with provider:
            with system_context("update two organizations"):
                repository = ArchivedOrderRepository()
                orders = [
                    Order.create(id=uuid4(), organization_id=org, code=str(uuid4()))
                    for org in organizations
                ]
                await repository.save_many(orders)
                orders = list(
                    (await repository.load_many([o.id for o in orders], lock=True)).values()
                )
                for order in orders:
                    order.void("system operation")
                await repository.save_many(orders)
    async with session_factory() as session:
        events = (await session.scalars(select(DomainEventModel))).all()
        archives = (await session.scalars(select(OrderArchiveModel))).all()
    assert {event.aggregate_id: event.organization_id for event in events} == {
        order.id: order.organization_id for order in orders
    }
    assert len(events) == 4
    assert {archive.id: archive.organization_id for archive in archives} == {
        order.id: order.organization_id for order in orders
    }
    assert len(archives) == 2
    assert "tenant filtering disabled: update two organizations" in caplog.text


@pytest.mark.parametrize("changed", [False, True])
async def test_same_loaded_aggregate_can_be_saved_after_nested_rollback(
    session_factory: Factory, doer: User, organization_id: UUID, changed: bool
) -> None:
    configure(session_factory=session_factory, event_bus=EventBus())
    order = await _created(session_factory, doer, organization_id)
    with unit_of_work_scope(
        session_factory, user=doer, organization_id=organization_id
    ) as provider:
        async with provider:
            repository = OrderRepository()
            loaded = await repository.load(order.id, lock=True)

            async def failed_batch() -> None:
                loaded.code = "batch"
                await repository.save(loaded)
                raise RuntimeError("force batch rollback")

            with pytest.raises(RuntimeError, match="force batch rollback"):
                await execute(failed_batch)
            loaded.code = "retry" if changed else order.code
            await execute(lambda: repository.save(loaded))
    with unit_of_work_scope(
        session_factory, user=doer, organization_id=organization_id
    ) as provider:
        async with provider:
            saved = await OrderRepository().load(order.id, lock=False)
    assert saved.code == ("retry" if changed else order.code)
    assert saved.version == loaded.version == (2 if changed else 1)
