from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd.context import User
from fast_ddd.repository import SearchPage
from fast_ddd_adapter.testing import unit_of_work_scope
from tests.adapter.models import Order, OrderModel, OrderRepository, Status

type Factory = async_sessionmaker[AsyncSession]


async def seed(factory: Factory, doer: User, org: UUID, codes: Sequence[str]) -> list[Order]:
    orders: list[Order] = []
    with unit_of_work_scope(factory, user=doer, organization_id=org) as provider:
        async with provider:
            for code in codes:
                order = Order.create(id=uuid4(), organization_id=org, code=code)
                await OrderRepository().save(order)
                orders.append(order)
    return orders


async def search(
    factory: Factory,
    doer: User,
    org: UUID,
    *,
    filters: Sequence[ColumnElement[bool]] = (),
    fields: Sequence[str] = (),
    keys: Sequence[str] = (),
    sort_by: Sequence[str] = (),
    offset: int = 0,
    limit: int = 10,
) -> SearchPage[Order]:
    with unit_of_work_scope(factory, user=doer, organization_id=org) as provider:
        async with provider:
            return await OrderRepository().search(
                filters,
                search_key_fields=fields,
                search_keys=keys,
                sort_by=sort_by,
                offset=offset,
                limit=limit,
            )


def codes(page: SearchPage[Order]) -> list[str]:
    return [order.code for order in page.items]


async def test_search_pages_sorts_and_filters_by_tenant(
    session_factory: Factory, doer: User, organization_id: UUID
) -> None:
    await seed(session_factory, doer, organization_id, ["b-2", "a-1", "c-3"])
    await seed(session_factory, doer, uuid4(), ["a-other"])

    newest_first = await search(session_factory, doer, organization_id)
    by_code = await search(session_factory, doer, organization_id, sort_by=["code"], limit=2)
    second_page = await search(
        session_factory, doer, organization_id, sort_by=["-code"], offset=1, limit=1
    )

    assert newest_first.total == 3
    assert codes(newest_first) == ["c-3", "a-1", "b-2"]
    assert (by_code.total, codes(by_code)) == (3, ["a-1", "b-2"])
    assert codes(second_page) == ["b-2"]


async def test_search_key_operators_and_unknown_fields(
    session_factory: Factory, doer: User, organization_id: UUID
) -> None:
    orders = await seed(session_factory, doer, organization_id, ["inv-10", "x-inv", "inv-2"])

    async def matching(fields: Sequence[str], keys: Sequence[str]) -> list[str]:
        page = await search(
            session_factory, doer, organization_id, fields=fields, keys=keys, sort_by=["code"]
        )
        return codes(page)

    assert await matching(["code"], ["inv"]) == ["inv-10", "inv-2", "x-inv"]
    assert await matching(["starts:code"], ["inv", "x-"]) == ["inv-10", "inv-2", "x-inv"]
    assert await matching(["ends:code"], ["-2", "inv"]) == ["inv-2", "x-inv"]
    assert await matching(["equals:code"], ["inv-1"]) == []
    assert await matching(["equals:code"], ["inv-1.*"]) == []
    assert await matching(["equals:id"], [str(orders[1].id)]) == ["x-inv"]
    assert await matching(["unknown"], ["inv"]) == ["inv-10", "inv-2", "x-inv"]


async def test_search_combines_service_filters(
    session_factory: Factory, doer: User, organization_id: UUID
) -> None:
    await seed(session_factory, doer, organization_id, ["a", "b"])

    page = await search(
        session_factory,
        doer,
        organization_id,
        filters=[OrderModel.status == Status.VOIDED.value],
    )

    assert page == SearchPage(total=0, items=[])
