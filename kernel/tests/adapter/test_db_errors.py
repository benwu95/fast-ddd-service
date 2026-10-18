import asyncio
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd.batch import BatchItem, BatchResult
from fast_ddd.context import User
from fast_ddd.errors import AggregateAlreadyExists, DomainError, ErrorKind, LockConflict
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter import db_errors
from fast_ddd_adapter.controller import execute, run_batch
from fast_ddd_adapter.infrastructure import configure
from fast_ddd_adapter.session import current_session_provider
from fast_ddd_adapter.testing import unit_of_work_scope
from tests.adapter.models import Order, OrderRepository
from tests.adapter.use_cases import OrderUseCase

type Factory = async_sessionmaker[AsyncSession]


@dataclass
class CodeConflict(DomainError):
    code: ClassVar[str] = "kernel_test.order.code_conflict"
    kind: ClassVar[ErrorKind] = ErrorKind.CONFLICT
    message: ClassVar[str] = "The order code is already used"


async def test_registered_constraint_translates_real_unique_violation(
    session_factory: Factory,
    doer: User,
    organization_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db_errors, "_constraint_errors", {})
    db_errors.register_constraint_error("uq_kernel_test_order_code", CodeConflict)
    configure(session_factory=session_factory, event_bus=EventBus())
    use_case = OrderUseCase(OrderRepository())
    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
        await execute(lambda: use_case.create(uuid4(), organization_id, "taken"))
    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
        with pytest.raises(CodeConflict):
            await execute(lambda: use_case.create(uuid4(), organization_id, "taken"))
        result = await execute(lambda: use_case.create(uuid4(), organization_id, "available"))
    assert result.code == "available"


async def test_real_deadlock_becomes_lock_conflict(
    session_factory: Factory,
    doer: User,
    organization_id: UUID,
) -> None:
    configure(session_factory=session_factory, event_bus=EventBus())
    ids = [uuid4(), uuid4()]
    for order_id in ids:
        with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
            await execute(
                lambda order_id=order_id: OrderUseCase(OrderRepository()).create(
                    order_id, organization_id, str(order_id)
                )
            )
    locked = [asyncio.Event(), asyncio.Event()]

    async def contend(index: int) -> None:
        with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):

            async def operation() -> None:
                session = current_session_provider().session
                await session.execute(text("SET LOCAL lock_timeout = '3s'"))
                await session.execute(text("SET LOCAL deadlock_timeout = '50ms'"))
                await OrderRepository().load(ids[index], lock=True)
                locked[index].set()
                await locked[1 - index].wait()
                await OrderRepository().load(ids[1 - index], lock=True)

            await execute(operation)

    results = await asyncio.wait_for(
        asyncio.gather(contend(0), contend(1), return_exceptions=True), 10
    )
    errors = [result for result in results if isinstance(result, LockConflict)]
    assert len(errors) == 1
    assert sum(result is None for result in results) == 1
    cause = errors[0].__cause__
    assert isinstance(cause, DBAPIError)
    assert cause.orig is not None
    assert getattr(cause.orig.__cause__, "sqlstate", None) == "40P01"


async def test_whole_batch_lock_conflict_does_not_fall_back(
    session_factory: Factory,
    doer: User,
    organization_id: UUID,
) -> None:
    configure(session_factory=session_factory, event_bus=EventBus())
    calls: list[UUID] = []
    item = BatchItem(uuid4(), "reason")

    async def batch() -> BatchResult[UUID, Order]:
        raise LockConflict()

    async def single() -> Order:
        calls.append(item.id)
        raise AssertionError("lock conflicts must not fall back")

    with (
        unit_of_work_scope(session_factory, user=doer, organization_id=organization_id),
        pytest.raises(LockConflict),
    ):
        await run_batch([item], batch=lambda _: batch(), single=lambda _: single())
    assert calls == []


@pytest.mark.parametrize("registered", [True, False])
async def test_named_foreign_key_maps_only_when_registered(
    session_factory: Factory,
    doer: User,
    organization_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
    registered: bool,
) -> None:
    monkeypatch.setattr(db_errors, "_constraint_errors", {})
    if registered:
        db_errors.register_constraint_error(
            "fk_kernel_test_order_line_order_id_kernel_test_order", CodeConflict
        )
    configure(session_factory=session_factory, event_bus=EventBus())

    async def orphan_line() -> None:
        await current_session_provider().session.execute(
            text(
                "INSERT INTO kernel_test_order_line (line_id, order_id, qty) "
                "VALUES (:id, :parent, 1)"
            ),
            {"id": uuid4(), "parent": uuid4()},
        )

    with (
        unit_of_work_scope(session_factory, user=doer, organization_id=organization_id),
        pytest.raises(CodeConflict if registered else IntegrityError),
    ):
        await execute(orphan_line)


@pytest.mark.parametrize("sqlstate", ["23505", "23503"])
def test_primary_collision_inference_requires_unique_violation(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str
) -> None:
    monkeypatch.setattr(db_errors, "_primary_keys", {"pk_test": Order})
    monkeypatch.setattr(db_errors, "_constraint_errors", {})
    order_id = uuid4()

    class DriverError(Exception):
        constraint_name = "pk_test"
        detail = f"Key (id)=({order_id}) already exists."

        def __init__(self, state: str) -> None:
            self.sqlstate = state

    result = db_errors.to_domain_error(DBAPIError(None, None, DriverError(sqlstate)))
    if sqlstate == "23505":
        assert isinstance(result, AggregateAlreadyExists)
        assert result.aggregate_id == order_id
    else:
        assert result is None
