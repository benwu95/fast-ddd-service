from collections.abc import Callable, Sequence
from uuid import UUID

from fast_ddd.batch import (
    BatchItem,
    BatchResult,
    apply_batch,
    apply_event_batch,
    check_version,
    create_batch,
)
from fast_ddd.events import DomainEvent
from tests.adapter.models import Order, OrderRepository


class OrderUseCase:
    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    async def create(self, order_id: UUID, organization_id: UUID, code: str) -> Order:
        order = Order.create(id=order_id, organization_id=organization_id, code=code)
        await self._repository.save(order)
        return order

    async def create_many(
        self, organization_id: UUID, items: Sequence[BatchItem[UUID, str]]
    ) -> BatchResult[UUID, Order]:
        return await create_batch(
            self._repository,
            items,
            lambda order_id, code: Order.create(
                id=order_id, organization_id=organization_id, code=code
            ),
        )

    async def void(self, order_id: UUID, reason: str, expected_version: int | None) -> Order:
        order = await self._repository.load(order_id, lock=True)
        check_version(order, expected_version)
        order.void(reason)
        await self._repository.save(order)
        return order

    async def void_many(self, items: Sequence[BatchItem[UUID, str]]) -> BatchResult[UUID, Order]:
        return await apply_batch(
            self._repository, Order, items, lambda order, reason: order.void(reason)
        )

    async def apply_events[E: DomainEvent](
        self,
        events: Sequence[E],
        target: Callable[[E], UUID],
        apply: Callable[[Order, E], None],
    ) -> list[Order]:
        return await apply_event_batch(self._repository, Order, events, target, apply)
