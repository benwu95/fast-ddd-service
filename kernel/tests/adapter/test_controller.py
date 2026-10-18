import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fast_ddd.batch import BatchItem, BatchResult
from fast_ddd.context import User
from fast_ddd.errors import AggregateAlreadyExists, AggregateNotFound, LockConflict
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.controller import (
    EventHandlerFailedError,
    TransientBatchFailureError,
    UnexpectedFailure,
    execute,
    run_batch,
)
from fast_ddd_adapter.infrastructure import OutgoingMessage, configure
from fast_ddd_adapter.messaging import integration_message, publish_after_commit
from fast_ddd_adapter.session import AlreadySavedInThisCommandError, current_session_provider
from fast_ddd_adapter.testing import count_statements, unit_of_work_scope
from tests.adapter.models import (
    Order,
    OrderAlreadyVoided,
    OrderCreated,
    OrderModel,
    OrderRepository,
    OrderVoided,
)
from tests.adapter.use_cases import OrderUseCase

type Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
def bus(session_factory: Factory) -> EventBus:
    bus = EventBus()
    configure(session_factory=session_factory, event_bus=bus)
    return bus


def use_case() -> OrderUseCase:
    return OrderUseCase(OrderRepository())


async def create(factory: Factory, doer: User, org: UUID, code: str | None = None) -> Order:
    with unit_of_work_scope(factory, user=doer, organization_id=org):
        return await execute(lambda: use_case().create(uuid4(), org, code or str(uuid4())[:8]))


async def count_orders(factory: Factory) -> int:
    async with factory() as session:
        return len((await session.execute(select(OrderModel.id))).all())


async def test_events_are_dispatched_and_cascade_through_nested_commands(
    session_factory: Factory, bus: EventBus, doer: User, organization_id: UUID
) -> None:
    seen: list[str] = []
    after_commit: list[str] = []

    async def on_created(event: OrderCreated) -> None:
        seen.append(f"created:{event.code}")
        provider = current_session_provider()

        async def published() -> None:
            after_commit.append(event.code)

        provider.after_commit(published)
        if event.code == "parent":
            await execute(lambda: use_case().create(uuid4(), organization_id, "child"))

    bus.subscribe(OrderCreated, on_created)
    await create(session_factory, doer, organization_id, "parent")

    assert seen == ["created:parent", "created:child"]
    assert after_commit == ["parent", "child"]
    assert await count_orders(session_factory) == 2


async def test_handler_domain_error_is_an_unexpected_failure(
    session_factory: Factory, bus: EventBus, doer: User, organization_id: UUID
) -> None:
    async def reject(event: OrderCreated) -> None:
        raise OrderAlreadyVoided(order_id=event.aggregate_id or uuid4())

    bus.subscribe(OrderCreated, reject)
    with pytest.raises(EventHandlerFailedError):
        await create(session_factory, doer, organization_id)
    assert await count_orders(session_factory) == 0


async def test_handler_cannot_resave_the_commands_aggregate(
    session_factory: Factory, bus: EventBus, doer: User, organization_id: UUID
) -> None:
    async def resave(event: OrderCreated) -> None:
        assert event.aggregate_id is not None
        await execute(lambda: use_case().void(event.aggregate_id or uuid4(), "x", None))

    bus.subscribe(OrderCreated, resave)
    with pytest.raises(AlreadySavedInThisCommandError):
        await create(session_factory, doer, organization_id)


async def test_nested_command_failure_only_rolls_back_its_savepoint(
    session_factory: Factory, bus: EventBus, doer: User, organization_id: UUID
) -> None:
    existing = await create(session_factory, doer, organization_id, "taken")

    async def try_duplicate(event: OrderCreated) -> None:
        if event.code == "outer":
            with pytest.raises(AggregateAlreadyExists):
                await execute(lambda: use_case().create(existing.id, organization_id, "dup"))

    bus.subscribe(OrderCreated, try_duplicate)
    await create(session_factory, doer, organization_id, "outer")

    assert await count_orders(session_factory) == 2


@pytest.mark.usefixtures("bus")
async def test_lock_timeout_becomes_lock_conflict(
    session_factory: Factory, doer: User, organization_id: UUID
) -> None:
    order = await create(session_factory, doer, organization_id)
    holding = asyncio.Event()
    release = asyncio.Event()

    async def hold_lock() -> None:
        with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):

            async def lock() -> None:
                await OrderRepository().load(order.id, lock=True)
                holding.set()
                await release.wait()

            await execute(lock)

    holder = asyncio.create_task(hold_lock())
    await holding.wait()
    try:
        with (
            unit_of_work_scope(session_factory, user=doer, organization_id=organization_id),
            pytest.raises(LockConflict),
        ):
            await execute(lambda: use_case().void(order.id, "x", None))
    finally:
        release.set()
        await holder


@pytest.mark.usefixtures("bus")
async def test_batch_round_trips_do_not_grow_with_batch_size(
    session_factory: Factory,
    engine: AsyncEngine,
    doer: User,
    organization_id: UUID,
) -> None:
    async def void_batch(size: int) -> tuple[int, int]:
        orders = [await create(session_factory, doer, organization_id) for _ in range(size)]
        items = [BatchItem(o.id, "bulk", expected_version=1) for o in orders]
        new_items = [BatchItem(uuid4(), str(uuid4())[:8]) for _ in range(size)]
        with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
            with count_statements(engine) as voided:
                await run_batch(
                    items,
                    batch=use_case().void_many,
                    single=lambda i: use_case().void(i.id, i.payload, i.expected_version),
                )
            with count_statements(engine) as created:
                await run_batch(
                    new_items,
                    batch=lambda its: use_case().create_many(organization_id, its),
                    single=lambda i: use_case().create(i.id, organization_id, i.payload),
                )
        return voided.count, created.count

    assert await void_batch(1) == await void_batch(50)


async def test_batch_falls_back_per_item_on_integrity_error(
    session_factory: Factory, bus: EventBus, doer: User, organization_id: UUID
) -> None:
    existing = await create(session_factory, doer, organization_id)
    published: list[str] = []

    async def on_created(event: OrderCreated) -> None:
        async def publish() -> None:
            published.append(event.code)

        current_session_provider().after_commit(publish)

    bus.subscribe(OrderCreated, on_created)
    items = [BatchItem(uuid4(), "a1"), BatchItem(existing.id, "dup"), BatchItem(uuid4(), "a3")]
    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
        outcome = await run_batch(
            items,
            batch=lambda its: use_case().create_many(organization_id, its),
            single=lambda i: use_case().create(i.id, organization_id, i.payload),
        )

    results = list(outcome.results.values())
    assert isinstance(results[0], Order)
    assert isinstance(results[1], AggregateAlreadyExists)
    assert isinstance(results[2], Order)
    assert published == ["a1", "a3"]


@pytest.mark.usefixtures("bus")
async def test_batch_reports_domain_failures_per_item(
    session_factory: Factory, doer: User, organization_id: UUID
) -> None:
    ok = await create(session_factory, doer, organization_id)
    voided = await create(session_factory, doer, organization_id)
    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
        await execute(lambda: use_case().void(voided.id, "first", None))
        outcome = await run_batch(
            [BatchItem(ok.id, "r"), BatchItem(voided.id, "r"), BatchItem(uuid4(), "r")],
            batch=use_case().void_many,
            single=lambda i: use_case().void(i.id, i.payload, i.expected_version),
        )

    results = list(outcome.results.values())
    assert isinstance(results[0], Order)
    assert isinstance(results[1], OrderAlreadyVoided)
    assert isinstance(results[2], AggregateNotFound)


@pytest.mark.usefixtures("bus")
async def test_nested_batch_uses_savepoints_and_keeps_outer_work(
    session_factory: Factory, doer: User, organization_id: UUID
) -> None:
    existing = await create(session_factory, doer, organization_id)
    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id) as p:

        async def outer() -> None:
            await use_case().create(uuid4(), organization_id, "outer")
            outcome = await run_batch(
                [BatchItem(uuid4(), "n1"), BatchItem(existing.id, "dup")],
                batch=lambda its: use_case().create_many(organization_id, its),
                single=lambda i: use_case().create(i.id, organization_id, i.payload),
            )
            assert isinstance(list(outcome.results.values())[1], AggregateAlreadyExists)

        async with p:
            await outer()

    assert await count_orders(session_factory) == 3


async def test_fallback_discards_staged_messages_and_keeps_outer_effect_once(
    session_factory: Factory, bus: EventBus, doer: User, organization_id: UUID
) -> None:
    existing = await create(session_factory, doer, organization_id)
    messages: list[OutgoingMessage] = []

    class Recorder:
        async def publish(self, message: OutgoingMessage) -> None:
            messages.append(message)

    configure(session_factory=session_factory, event_bus=bus, publisher=Recorder())

    async def forward(event: OrderCreated) -> None:
        publish_after_commit(integration_message(event, exchange="test"))

    bus.subscribe(OrderCreated, forward)
    items = [BatchItem(uuid4(), "success"), BatchItem(existing.id, "duplicate")]

    async def batch_with_staged_message(
        batch_items: list[BatchItem[UUID, str]],
    ) -> BatchResult[UUID, Order]:
        publish_after_commit(OutgoingMessage("test", "discarded", {"code": "discarded"}, {}))
        return await use_case().create_many(organization_id, batch_items)

    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id) as p:
        async with p:
            await execute(lambda: use_case().create(uuid4(), organization_id, "outer"))
            outcome = await run_batch(
                items,
                batch=lambda values: batch_with_staged_message(list(values)),
                single=lambda item: use_case().create(item.id, organization_id, item.payload),
            )
            assert isinstance(outcome.results[items[1].id], AggregateAlreadyExists)
            assert messages == []

    assert [message.body["data"]["code"] for message in messages] == ["outer", "success"]
    assert await count_orders(session_factory) == 3


async def test_non_http_batch_raises_on_transient_failure(
    session_factory: Factory, bus: EventBus, doer: User, organization_id: UUID
) -> None:
    order = await create(session_factory, doer, organization_id)

    async def explode(event: OrderVoided) -> None:
        raise RuntimeError(f"handler crashed for {event.aggregate_id}")

    bus.subscribe(OrderVoided, explode)
    with (
        unit_of_work_scope(session_factory, user=doer, organization_id=organization_id),
        pytest.raises(TransientBatchFailureError),
    ):
        await run_batch(
            [BatchItem(order.id, "r")],
            batch=use_case().void_many,
            single=lambda i: use_case().void(i.id, i.payload, i.expected_version),
            raise_on_transient=True,
        )

    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
        outcome = await run_batch(
            [BatchItem(order.id, "r")],
            batch=use_case().void_many,
            single=lambda i: use_case().void(i.id, i.payload, i.expected_version),
        )
    assert isinstance(next(iter(outcome.results.values())), UnexpectedFailure)
