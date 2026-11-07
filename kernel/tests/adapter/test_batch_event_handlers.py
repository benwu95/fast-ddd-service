from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fast_ddd.batch import BatchItem, BatchResult
from fast_ddd.context import User, current_organization_id
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.controller import (
    BatchOutcome,
    EventChainLimitExceededError,
    UnexpectedFailure,
    execute,
    run_batch,
)
from fast_ddd_adapter.infrastructure import (
    OutgoingMessage,
    configure,
    infrastructure,
    system_context,
)
from fast_ddd_adapter.messaging import integration_message, publish_after_commit
from fast_ddd_adapter.orm import DomainEventModel
from fast_ddd_adapter.session import SessionProvider, current_session_provider
from fast_ddd_adapter.testing import count_statements, unit_of_work_scope
from tests.adapter.models import (
    Order,
    OrderCreated,
    OrderLineAdded,
    OrderModel,
    OrderRepository,
    OrderVoided,
    Status,
)
from tests.adapter.use_cases import OrderUseCase

type Factory = async_sessionmaker[AsyncSession]


def use_case() -> OrderUseCase:
    return OrderUseCase(OrderRepository())


def new_code() -> str:
    return uuid4().hex[:8]


def new_bus(factory: Factory, *, depth: int = 10, total: int = 10_000) -> EventBus:
    bus = EventBus()
    configure(
        session_factory=factory,
        event_bus=bus,
        max_event_chain_depth=depth,
        max_events_per_unit_of_work=total,
    )
    return bus


async def create_orders(factory: Factory, doer: User, org: UUID, count: int) -> list[Order]:
    """Seed orders with no handlers subscribed; call it before wiring the bus under test."""
    configure(session_factory=factory, event_bus=EventBus())
    items = [BatchItem(uuid4(), new_code()) for _ in range(count)]
    with unit_of_work_scope(factory, user=doer, organization_id=org):
        result = await execute(lambda: use_case().create_many(org, items))
    return [result.succeeded[item.id] for item in items]


async def load_orders(factory: Factory, doer: User, org: UUID, ids: list[UUID]) -> list[Order]:
    with unit_of_work_scope(factory, user=doer, organization_id=org):
        loaded = await execute(lambda: OrderRepository().load_many(ids, lock=False))
    return [loaded[i] for i in ids]


async def domain_events(factory: Factory, name: str) -> list[DomainEventModel]:
    async with factory() as session:
        rows = await session.scalars(select(DomainEventModel).where(DomainEventModel.name == name))
        return list(rows.all())


async def count_orders(factory: Factory) -> int:
    async with factory() as session:
        return len((await session.execute(select(OrderModel.id))).all())


def create_sources(
    org: UUID, items: Sequence[BatchItem[UUID, str]]
) -> Callable[[], Awaitable[BatchOutcome[UUID, Order]]]:
    return lambda: run_batch(
        items,
        batch=lambda batch: use_case().create_many(org, batch),
        single=lambda item: use_case().create(item.id, org, item.payload),
    )


async def test_batch_handler_chain_round_trips_do_not_grow_with_batch_size(
    session_factory: Factory, engine: AsyncEngine, doer: User, organization_id: UUID
) -> None:
    async def run_chain(size: int) -> int:
        targets = await create_orders(session_factory, doer, organization_id, size)
        finals = await create_orders(session_factory, doer, organization_id, size)
        sources = [BatchItem(uuid4(), new_code()) for _ in range(size)]
        target_of = {s.payload: t.id for s, t in zip(sources, targets, strict=True)}
        final_of: dict[UUID | None, UUID] = {
            t.id: f.id for t, f in zip(targets, finals, strict=True)
        }
        bus = new_bus(session_factory)

        async def add_lines(events: list[OrderCreated]) -> None:
            await execute(
                lambda: use_case().apply_events(
                    events,
                    lambda e: target_of[e.code],
                    lambda order, _: order.add_line(uuid4(), 1),
                )
            )

        async def void_finals(events: list[OrderLineAdded]) -> None:
            await execute(
                lambda: use_case().apply_events(
                    events,
                    lambda e: final_of[e.aggregate_id],
                    lambda order, _: order.void("chain"),
                )
            )

        bus.subscribe_batch(OrderCreated, add_lines)
        bus.subscribe_batch(OrderLineAdded, void_finals)
        with (
            unit_of_work_scope(session_factory, user=doer, organization_id=organization_id),
            count_statements(engine) as counter,
        ):
            outcome = await create_sources(organization_id, sources)()

        assert all(isinstance(r, Order) for r in outcome.results.values())
        reloaded = await load_orders(
            session_factory, doer, organization_id, [o.id for o in targets + finals]
        )
        assert [len(o.lines) for o in reloaded[:size]] == [1] * size
        assert {o.status for o in reloaded[size:]} == {Status.VOIDED}
        return counter.count

    assert await run_chain(1) == await run_chain(50)


async def test_shared_target_is_loaded_and_saved_once_with_per_event_parents(
    session_factory: Factory, engine: AsyncEngine, doer: User, organization_id: UUID
) -> None:
    (target,) = await create_orders(session_factory, doer, organization_id, 1)
    sources = [BatchItem(uuid4(), new_code()) for _ in range(2)]
    line_of = {s.payload: uuid4() for s in sources}
    bus = new_bus(session_factory)

    async def add_lines(events: list[OrderCreated]) -> None:
        await execute(
            lambda: use_case().apply_events(
                events, lambda _: target.id, lambda order, e: order.add_line(line_of[e.code], 1)
            )
        )

    bus.subscribe_batch(OrderCreated, add_lines)
    with (
        unit_of_work_scope(session_factory, user=doer, organization_id=organization_id),
        count_statements(engine) as counter,
    ):
        await create_sources(organization_id, sources)()

    assert sum("FOR UPDATE" in s for s in counter.statements) == 1
    (reloaded,) = await load_orders(session_factory, doer, organization_id, [target.id])
    assert reloaded.version == 2
    assert {line.line_id for line in reloaded.lines} == set(line_of.values())
    created = {
        row.aggregate_id: row.event_id
        for row in await domain_events(session_factory, "OrderCreated")
    }
    added = {
        row.body["line_id"]: row.parent_event_id
        for row in await domain_events(session_factory, "OrderLineAdded")
    }
    assert added == {str(line_of[s.payload]): created[s.id] for s in sources}


async def test_batch_handler_is_called_once_per_organization(
    session_factory: Factory, doer: User
) -> None:
    org_a, org_b = uuid4(), uuid4()
    with unit_of_work_scope(session_factory, user=doer, organization_id=None):
        orders = [
            Order.create(id=uuid4(), organization_id=org, code=new_code())
            for org in (org_a, org_b, org_a)
        ]
    bus = new_bus(session_factory)
    seen: list[tuple[UUID | None, list[UUID], set[UUID]]] = []

    async def inspect(events: list[OrderCreated]) -> None:
        visible = await OrderRepository().load_many([o.id for o in orders], lock=False)
        seen.append(
            (current_organization_id(), [e.aggregate_id or uuid4() for e in events], set(visible))
        )

    bus.subscribe_batch(OrderCreated, inspect)
    with (
        unit_of_work_scope(session_factory, user=doer, organization_id=None),
        system_context("create orders of two organizations"),
    ):
        await execute(lambda: OrderRepository().save_many(orders))

    first, second, third = (o.id for o in orders)
    assert seen == [(org_a, [first, third], {first, third}), (org_b, [second], {second})]


@dataclass(frozen=True)
class FallbackRun:
    outcome: list[str]
    target_lines: list[int]
    target_versions: list[int]
    causes: set[tuple[int | None, int | None]]
    messages: list[int]


async def run_failing_chain(
    factory: Factory, doer: User, org: UUID, *, failure: str, batched: bool
) -> tuple[FallbackRun, list[int]]:
    targets = await create_orders(factory, doer, org, 3)
    sources = [BatchItem(uuid4(), new_code()) for _ in range(3)]
    failing = sources[1].payload
    target_of = {s.payload: t.id for s, t in zip(sources, targets, strict=True)}
    if failure == "missing target":
        target_of[failing] = uuid4()
    messages: list[OutgoingMessage] = []

    class Recorder:
        async def publish(self, message: OutgoingMessage) -> None:
            messages.append(message)

    bus = EventBus()
    configure(session_factory=factory, event_bus=bus, publisher=Recorder())
    sizes: list[int] = []

    async def handle(events: list[OrderCreated]) -> None:
        sizes.append(len(events))
        if failure == "handler error" and any(e.code == failing for e in events):
            raise RuntimeError("handler failed")
        for event in events:
            publish_after_commit(integration_message(event, exchange="test"))
        await execute(
            lambda: use_case().apply_events(
                events, lambda e: target_of[e.code], lambda order, _: order.add_line(uuid4(), 1)
            )
        )

    async def handle_one(event: OrderCreated) -> None:
        await handle([event])

    if batched:
        bus.subscribe_batch(OrderCreated, handle)
    else:
        bus.subscribe(OrderCreated, handle_one)
    with unit_of_work_scope(factory, user=doer, organization_id=org):
        outcome = await run_batch(
            sources,
            batch=lambda batch: use_case().create_many(org, batch),
            single=lambda item: use_case().create(item.id, org, item.payload),
        )

    reloaded = await load_orders(factory, doer, org, [t.id for t in targets])
    source_index: dict[UUID | None, int] = {s.id: i for i, s in enumerate(sources)}
    target_index: dict[UUID | None, int] = {t.id: i for i, t in enumerate(targets)}
    created: dict[UUID | None, UUID | None] = {
        row.event_id: row.aggregate_id for row in await domain_events(factory, "OrderCreated")
    }
    causes = {
        (target_index.get(row.aggregate_id), source_index.get(created.get(row.parent_event_id)))
        for row in await domain_events(factory, "OrderLineAdded")
    } - {(None, None)}
    run = FallbackRun(
        outcome=[type(outcome.results[s.id]).__name__ for s in sources],
        target_lines=[len(o.lines) for o in reloaded],
        target_versions=[o.version for o in reloaded],
        causes=causes,
        messages=[[s.payload for s in sources].index(m.body["data"]["code"]) for m in messages],
    )
    return run, sizes


@pytest.mark.parametrize("failure", ["handler error", "missing target"])
async def test_failed_batch_handler_falls_back_and_matches_single_handlers(
    session_factory: Factory, doer: User, organization_id: UUID, failure: str
) -> None:
    batched, sizes = await run_failing_chain(
        session_factory, doer, organization_id, failure=failure, batched=True
    )
    single, _ = await run_failing_chain(
        session_factory, doer, organization_id, failure=failure, batched=False
    )

    assert sizes == [3, 1, 1, 1]
    assert batched.outcome == ["Order", UnexpectedFailure.__name__, "Order"]
    assert batched.target_lines == [1, 0, 1]
    assert batched.target_versions == [2, 1, 2]
    assert batched.causes == {(0, 0), (2, 2)}
    assert batched == single


async def run_cycle(
    factory: Factory, doer: User, org: UUID, *, batched: bool, stop_after: int, depth: int
) -> list[str]:
    """OrderCreated → void a fresh pool order → OrderVoided → create an order → OrderCreated…"""
    pool = await create_orders(factory, doer, org, 8)
    bus = new_bus(factory, depth=depth)
    calls: list[str] = []

    async def without_events() -> None:
        await execute(lambda: OrderRepository().load_many([pool[0].id], lock=False))

    async def on_created(_events: Sequence[OrderCreated]) -> None:
        calls.append("created")
        if len(calls) >= stop_after:
            await without_events()
            return
        victim = pool.pop()
        await execute(lambda: use_case().void(victim.id, "cycle", None))

    async def on_voided(_events: Sequence[OrderVoided]) -> None:
        calls.append("voided")
        if len(calls) >= stop_after:
            await without_events()
            return
        await execute(lambda: use_case().create(uuid4(), org, new_code()))

    if batched:
        bus.subscribe_batch(OrderCreated, on_created)
        bus.subscribe_batch(OrderVoided, on_voided)
    else:
        bus.subscribe(OrderCreated, lambda event: on_created([event]))
        bus.subscribe(OrderVoided, lambda event: on_voided([event]))
    with unit_of_work_scope(factory, user=doer, organization_id=org):
        await execute(lambda: use_case().create(uuid4(), org, new_code()))
    return calls


@pytest.mark.parametrize("batched", [False, True], ids=["single", "batch"])
@pytest.mark.parametrize("depth", [10, 3, 12], ids=["default", "lowered", "raised"])
async def test_event_chain_depth_limit_stops_cycles(
    session_factory: Factory, doer: User, organization_id: UUID, batched: bool, depth: int
) -> None:
    limit = depth
    calls = await run_cycle(
        session_factory, doer, organization_id, batched=batched, stop_after=limit, depth=depth
    )
    assert len(calls) == limit

    await clear_orders(session_factory)
    with pytest.raises(EventChainLimitExceededError, match=f"generation {limit + 1}"):
        await run_cycle(
            session_factory, doer, organization_id, batched=batched, stop_after=99, depth=depth
        )
    assert await count_orders(session_factory) == 8


async def run_inside[T](
    provider: SessionProvider, *, nested: bool, command: Callable[[], Awaitable[T]]
) -> T:
    """Run the command as its own unit of work, or nested in an already open one."""
    if not nested:
        return await command()
    async with provider:
        return await command()


@pytest.mark.parametrize("nested", [False, True], ids=["outermost", "nested"])
async def test_run_batch_raises_a_chain_limit_hit_by_the_whole_batch(
    session_factory: Factory, doer: User, organization_id: UUID, nested: bool
) -> None:
    bus = new_bus(session_factory, depth=2)
    seen: list[int] = []

    async def recreate(events: list[OrderCreated]) -> None:
        seen.append(len(events))
        await execute(
            lambda: use_case().create_many(
                organization_id, [BatchItem(uuid4(), new_code()) for _ in events]
            )
        )

    bus.subscribe_batch(OrderCreated, recreate)
    items = [BatchItem(uuid4(), new_code()) for _ in range(3)]
    with (
        unit_of_work_scope(session_factory, user=doer, organization_id=organization_id) as p,
        pytest.raises(EventChainLimitExceededError),
    ):
        await run_inside(p, nested=nested, command=create_sources(organization_id, items))

    assert seen == [3, 3]
    assert await count_orders(session_factory) == 0


@pytest.mark.parametrize("nested", [False, True], ids=["outermost", "nested"])
async def test_chain_limit_in_the_fallback_fails_one_item_only_when_items_commit_alone(
    session_factory: Factory, doer: User, organization_id: UUID, nested: bool
) -> None:
    bus = new_bus(session_factory, depth=2)
    items = [BatchItem(uuid4(), new_code()) for _ in range(3)]
    looping = items[1].payload

    async def loop_one(events: list[OrderCreated]) -> None:
        if len(events) > 1:
            raise RuntimeError("only single events reach the chain")
        if events[0].code == looping or events[0].code.startswith("loop-"):
            await execute(lambda: use_case().create(uuid4(), organization_id, f"loop-{new_code()}"))

    bus.subscribe_batch(OrderCreated, loop_one)
    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id) as p:
        if nested:
            with pytest.raises(EventChainLimitExceededError):
                await run_inside(p, nested=True, command=create_sources(organization_id, items))
        else:
            outcome = await create_sources(organization_id, items)()
            kinds = [type(outcome.results[item.id]).__name__ for item in items]
            assert kinds == ["Order", UnexpectedFailure.__name__, "Order"]

    assert await count_orders(session_factory) == (0 if nested else 2)


async def record_new_orders(count: int) -> None:
    provider = current_session_provider()
    for order in (Order.create(id=uuid4(), organization_id=None, code="") for _ in range(count)):
        provider.record_saved(order)


@pytest.mark.parametrize(
    ("total", "events", "allowed"),
    [(10_000, 10_000, True), (10_000, 10_001, False), (20_000, 10_001, True)],
)
async def test_event_total_limit_defaults_and_is_configurable(
    session_factory: Factory,
    doer: User,
    organization_id: UUID,
    total: int,
    events: int,
    allowed: bool,
) -> None:
    new_bus(session_factory, total=total)
    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
        if allowed:
            await execute(lambda: record_new_orders(events))
        else:
            with pytest.raises(EventChainLimitExceededError, match=f"{events} events"):
                await execute(lambda: record_new_orders(events))


@pytest.mark.parametrize("batched", [False, True], ids=["single", "batch"])
@pytest.mark.parametrize(("roots", "allowed"), [(2, True), (3, False)])
async def test_event_total_counts_every_generation(
    session_factory: Factory,
    doer: User,
    organization_id: UUID,
    batched: bool,
    roots: int,
    allowed: bool,
) -> None:
    bus = new_bus(session_factory, total=4)

    async def spawn(events: Sequence[OrderCreated]) -> None:
        children = [
            BatchItem(uuid4(), f"child-{new_code()}") for e in events if e.code.startswith("root")
        ]
        if children:
            await execute(lambda: use_case().create_many(organization_id, children))

    if batched:
        bus.subscribe_batch(OrderCreated, spawn)
    else:
        bus.subscribe(OrderCreated, lambda event: spawn([event]))
    roots_items = [BatchItem(uuid4(), f"root-{new_code()}") for _ in range(roots)]
    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
        if allowed:
            await execute(lambda: use_case().create_many(organization_id, roots_items))
        else:
            with pytest.raises(EventChainLimitExceededError):
                await execute(lambda: use_case().create_many(organization_id, roots_items))
    assert await count_orders(session_factory) == (2 * roots if allowed else 0)


@pytest.mark.parametrize("nested", [False, True], ids=["outermost", "nested"])
async def test_rolled_back_dispatches_do_not_count_toward_the_total(
    session_factory: Factory, doer: User, organization_id: UUID, nested: bool
) -> None:
    bus = new_bus(session_factory, depth=1, total=3)

    async def reject_groups(events: list[OrderCreated]) -> None:
        if len(events) > 1:
            raise RuntimeError("only single events succeed")

    bus.subscribe_batch(OrderCreated, reject_groups)
    size = 2 if nested else 3
    items = [BatchItem(uuid4(), new_code()) for _ in range(size)]
    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id) as p:
        if nested:
            async with p:
                await execute(lambda: use_case().create(uuid4(), organization_id, new_code()))
                assert p.dispatched_events == 1
                outcome = await create_sources(organization_id, items)()
                assert (p.dispatched_events, p.dispatch_depth) == (3, 0)
        else:
            outcome = await create_sources(organization_id, items)()

    assert all(isinstance(r, Order) for r in outcome.results.values())
    assert await count_orders(session_factory) == 3


def configure_limit(factory: Factory, name: str, value: int) -> None:
    if name == "max_event_chain_depth":
        configure(session_factory=factory, event_bus=EventBus(), max_event_chain_depth=value)
    else:
        configure(session_factory=factory, event_bus=EventBus(), max_events_per_unit_of_work=value)


async def test_each_committed_unit_of_work_starts_a_new_event_total(
    session_factory: Factory, doer: User, organization_id: UUID
) -> None:
    new_bus(session_factory, total=1)
    items = [BatchItem(uuid4(), new_code()) for _ in range(3)]

    async def fail_before_saving(
        _items: Sequence[BatchItem[UUID, str]],
    ) -> BatchResult[UUID, Order]:
        raise RuntimeError("the whole batch fails before any event")

    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
        outcome = await run_batch(
            items,
            batch=fail_before_saving,
            single=lambda item: use_case().create(item.id, organization_id, item.payload),
        )

    assert all(isinstance(r, Order) for r in outcome.results.values())
    assert await count_orders(session_factory) == 3


@pytest.mark.parametrize("name", ["max_event_chain_depth", "max_events_per_unit_of_work"])
@pytest.mark.parametrize("value", [0, -1])
def test_configure_rejects_limits_below_one(
    session_factory: Factory, name: str, value: int
) -> None:
    configure(session_factory=session_factory, event_bus=EventBus())
    before = infrastructure()
    assert (before.max_event_chain_depth, before.max_events_per_unit_of_work) == (10, 10_000)

    with pytest.raises(ValueError, match=name):
        configure_limit(session_factory, name, value)
    assert infrastructure() is before


async def clear_orders(factory: Factory) -> None:
    async with factory.begin() as session:
        await session.execute(delete(DomainEventModel))
        await session.execute(delete(OrderModel))
