from collections.abc import Awaitable, Callable
from decimal import Decimal
from uuid import UUID, uuid4

import pendulum
import pytest
from fast_ddd.context import User
from fast_ddd.repository import SearchPage
from fast_ddd_adapter.infrastructure import system_context
from fast_ddd_adapter.repository import TenantContextMissingError
from fast_ddd_adapter.testing import count_statements, unit_of_work_scope
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.adapter.repository.billing.invoice_repository import InvoiceRepository, InvoiceTotals
from app.core.billing.domain.invoice import (
    CustomerId,
    Invoice,
    InvoiceContent,
    InvoiceId,
    InvoiceLine,
    InvoiceStatus,
)
from tests.support import content

type Factory = async_sessionmaker[AsyncSession]

DOER = User(id="user-1")


async def in_unit_of_work[T](
    factory: Factory, organization_id: UUID | None, work: Callable[[], Awaitable[T]]
) -> T:
    with unit_of_work_scope(factory, user=DOER, organization_id=organization_id) as provider:
        async with provider:
            return await work()


async def issue(
    factory: Factory, organization_id: UUID, invoice_content: InvoiceContent
) -> Invoice:
    invoice = Invoice.issue(
        id=InvoiceId(uuid4()), organization_id=organization_id, content=invoice_content, doer=DOER
    )
    await in_unit_of_work(factory, organization_id, lambda: InvoiceRepository().save(invoice))
    return invoice


async def load(
    factory: Factory, organization_id: UUID | None, invoice_id: InvoiceId
) -> Invoice | None:
    found = await in_unit_of_work(
        factory,
        organization_id,
        lambda: InvoiceRepository().load_many([invoice_id], lock=False),
    )
    return found.get(invoice_id)


async def test_mapping_round_trips_including_lines(
    session_factory: Factory, organization_id: UUID
) -> None:
    lines = (InvoiceLine("B", 3, Decimal("0.10")), InvoiceLine("A", 1, Decimal("99999.99")))
    invoice = await issue(session_factory, organization_id, content(lines=lines, note="n"))

    loaded = await load(session_factory, organization_id, invoice.id)

    assert loaded is not None
    assert loaded.content == invoice.content
    assert loaded.total == Decimal("100000.29")
    assert (loaded.status, loaded.version) == (InvoiceStatus.ACTIVE, 1)
    assert loaded.created_at == loaded.updated_at == invoice.created_at


async def test_version_follows_real_changes_including_lines_only(
    session_factory: Factory, organization_id: UUID
) -> None:
    invoice = await issue(session_factory, organization_id, content())

    async def save(change: Callable[[Invoice], None]) -> Invoice:
        async def work() -> Invoice:
            repository = InvoiceRepository()
            current = await repository.load(invoice.id, lock=True)
            change(current)
            await repository.save(current)
            return current

        return await in_unit_of_work(session_factory, organization_id, work)

    unchanged = await save(lambda _: None)
    relined = await save(
        lambda current: current.update(
            InvoiceContent(
                number=current.content.number,
                customer=current.content.customer,
                lines=(InvoiceLine("Consulting", 3, Decimal("150.00")),),
            ),
            DOER,
        )
    )
    reloaded = await load(session_factory, organization_id, invoice.id)

    assert unchanged.version == 1
    assert relined.version == 2
    assert relined.updated_at > invoice.updated_at
    assert reloaded is not None
    assert (reloaded.version, reloaded.updated_at) == (2, relined.updated_at)
    assert reloaded.total == Decimal("450.00")


async def test_other_organizations_cannot_see_the_invoice(
    session_factory: Factory, organization_id: UUID
) -> None:
    invoice = await issue(session_factory, organization_id, content())

    assert await load(session_factory, uuid4(), invoice.id) is None
    with pytest.raises(TenantContextMissingError):
        await load(session_factory, None, invoice.id)


async def test_locked_loads_use_a_fixed_order(
    session_factory: Factory, engine: AsyncEngine, organization_id: UUID
) -> None:
    invoices = [await issue(session_factory, organization_id, content(f"N-{i}")) for i in range(3)]

    with count_statements(engine) as counter:
        await in_unit_of_work(
            session_factory,
            organization_id,
            lambda: InvoiceRepository().load_many([i.id for i in invoices], lock=True),
        )

    locking = counter.statements[0]
    assert "ORDER BY billing_invoice.id" in locking
    assert "FOR UPDATE" in locking


async def test_search_filters_sorts_and_pages(
    session_factory: Factory, organization_id: UUID
) -> None:
    customer = CustomerId(uuid4())
    await issue(session_factory, organization_id, content("INV-2", customer_id=customer))
    await issue(session_factory, organization_id, content("INV-1", customer_id=customer))
    await issue(session_factory, organization_id, content("CN-1"))
    await issue(session_factory, uuid4(), content("INV-3", customer_id=customer))

    def numbers(
        search: Callable[[InvoiceRepository], Awaitable[SearchPage[Invoice]]],
    ) -> Awaitable[tuple[int, list[str]]]:
        async def work() -> tuple[int, list[str]]:
            page = await search(InvoiceRepository())
            return page.total, [invoice.content.number for invoice in page.items]

        return in_unit_of_work(session_factory, organization_id, work)

    assert await numbers(lambda r: r.search_invoices(sort_by=["number"], limit=10)) == (
        3,
        ["CN-1", "INV-1", "INV-2"],
    )
    assert await numbers(
        lambda r: r.search_invoices(customer_ids=[customer], sort_by=["-number"], limit=10)
    ) == (2, ["INV-2", "INV-1"])
    assert await numbers(
        lambda r: r.search_invoices(
            search_key_fields=["starts:number"], search_keys=["CN"], limit=10
        )
    ) == (1, ["CN-1"])
    assert await numbers(
        lambda r: r.search_invoices(statuses=[InvoiceStatus.VOIDED], limit=10)
    ) == (0, [])
    assert await numbers(lambda r: r.search_invoices(sort_by=["number"], offset=2, limit=1)) == (
        3,
        ["INV-2"],
    )


async def test_daily_totals_per_organization(session_factory: Factory) -> None:
    first, second = uuid4(), uuid4()
    await issue(session_factory, first, content("A"))
    await issue(session_factory, first, content("B", lines=(InvoiceLine("x", 1, Decimal("1")),)))
    await issue(session_factory, second, content("C"))
    since = pendulum.now("UTC").subtract(hours=1)

    async def organizations() -> list[UUID]:
        with system_context("test"):
            return await InvoiceRepository().organizations_issuing_since(since)

    assert sorted(await in_unit_of_work(session_factory, None, organizations)) == sorted(
        [first, second]
    )
    totals = await in_unit_of_work(
        session_factory, first, lambda: InvoiceRepository().totals_since(since)
    )
    assert totals == InvoiceTotals(count=2, amount=Decimal("301.00"))
