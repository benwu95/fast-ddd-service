import asyncio
import json
from collections import Counter
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from typing import Any
from uuid import UUID, uuid4

import aio_pika
import asyncpg
import httpx2
import pytest
from fast_ddd.context import User
from fast_ddd_adapter.infrastructure import configure, infrastructure
from fast_ddd_adapter.messaging import create_broker
from fast_ddd_adapter.orm import DomainEventModel, ProcessedMessage
from fast_ddd_adapter.session import SessionProvider, current_session_provider
from fast_ddd_adapter.testing import unit_of_work_scope
from fast_ddd_port.subscriber import declare_dead_letter_queue
from fast_ddd_port.testing import TokenFactory
from faststream.rabbit import RabbitBroker
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from app.adapter.controller.billing.invoice_commands import CreateInvoiceCommand
from app.adapter.controller.billing.invoice_controller import BULK_CHUNK_SIZE, InvoiceController
from app.adapter.controller.billing.task_names import VOID_INVOICES
from app.bootstrap import build_runtime
from app.core.billing.domain.events import InvoiceVoided
from app.core.billing.domain.invoice import Invoice, InvoiceStatus
from app.main import build_app
from app.port.message_queue.customer.customer_subscriber import (
    CUSTOMER_DEACTIVATED_QUEUE,
    CUSTOMER_EXCHANGE,
)
from app.settings import Settings
from app.wiring import wire_consumer
from tests.conftest import Infrastructure
from tests.port.test_invoice_tasks import drain, jobs
from tests.support import content

type Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(scope="session")
def amqp_url() -> Generator[str]:
    container = (
        DockerContainer("rabbitmq:4-management")
        .with_exposed_ports(5672)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    with container:
        host, port = container.get_container_host_ip(), container.get_exposed_port(5672)
        yield f"amqp://guest:guest@{host}:{port}/"


@pytest.fixture
async def broker(
    amqp_url: str, session_factory: Factory, infrastructure: Infrastructure
) -> AsyncGenerator[RabbitBroker]:
    del infrastructure
    broker = create_broker(amqp_url)
    queues = wire_consumer(broker, session_factory)
    await broker.start()
    for queue in queues:
        await declare_dead_letter_queue(broker, queue)
    await dead_letters(amqp_url)
    yield broker
    await broker.stop()


def envelope(organization_id: UUID | None, data: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "eventId": str(uuid4()),
        "eventName": "CustomerDeactivated",
        "eventVersion": 1,
        "organizationId": str(organization_id) if organization_id else None,
        "occurredAt": "2026-10-18T00:00:00.000Z",
        "data": data,
        **extra,
    }


async def send(broker: RabbitBroker, body: dict[str, Any]) -> None:
    await broker.publish(body, exchange=CUSTOMER_EXCHANGE, routing_key="CustomerDeactivated")


async def dead_letters(amqp_url: str) -> list[dict[str, Any]]:
    connection = await aio_pika.connect(amqp_url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.get_queue(f"{CUSTOMER_DEACTIVATED_QUEUE}.dlq", ensure=False)
        bodies: list[dict[str, Any]] = []
        while (message := await queue.get(no_ack=True, fail=False)) is not None:
            bodies.append(json.loads(message.body))
        return bodies


async def eventually(condition: Callable[[], Awaitable[bool]], within: float = 10.0) -> None:
    for _ in range(int(within / 0.1)):
        if await condition():
            return
        await asyncio.sleep(0.1)
    raise TimeoutError("condition not met")


async def processed(factory: Factory) -> int:
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(ProcessedMessage)) or 0


async def invoices_of(
    factory: Factory, organization_id: UUID, customer: UUID, count: int = 2
) -> list[Invoice]:
    controller = InvoiceController()
    with unit_of_work_scope(factory, user=User(id="t"), organization_id=organization_id):
        return [
            await controller.create(
                CreateInvoiceCommand(None, content(f"N-{uuid4().hex[:8]}", customer_id=customer))
            )
            for _ in range(count)
        ]


async def statuses(factory: Factory, organization_id: UUID, invoices: list[Invoice]) -> set[str]:
    controller = InvoiceController()
    with unit_of_work_scope(factory, user=User(id="t"), organization_id=organization_id):
        return {(await controller.get(invoice.id)).status.value for invoice in invoices}


async def processed_once(factory: Factory) -> None:
    async def done() -> bool:
        return await processed(factory) == 1

    await eventually(done)
    await asyncio.sleep(0.5)


async def test_deactivated_customer_has_its_invoices_voided_once(
    broker: RabbitBroker,
    session_factory: Factory,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    customer = uuid4()
    targeted = await invoices_of(session_factory, organization_id, customer)
    other_customer = await invoices_of(session_factory, organization_id, uuid4())
    other_organization = uuid4()
    same_customer_elsewhere = await invoices_of(session_factory, other_organization, customer)
    message = envelope(organization_id, {"customerId": str(customer), "addedLater": True})

    await send(broker, message)
    await send(broker, message)
    await processed_once(session_factory)
    await drain(connection, session_factory)

    assert await statuses(session_factory, organization_id, targeted) == {
        InvoiceStatus.VOIDED.value
    }
    assert await processed(session_factory) == 1
    assert await statuses(session_factory, organization_id, other_customer) == {
        InvoiceStatus.ACTIVE.value
    }
    assert await statuses(session_factory, other_organization, same_customer_elsewhere) == {
        InvoiceStatus.ACTIVE.value
    }


async def test_invoices_past_the_event_limit_are_voided_one_chunk_per_unit_of_work(
    broker: RabbitBroker,
    amqp_url: str,
    session_factory: Factory,
    connection: asyncpg.Connection,
    organization_id: UUID,
) -> None:
    kernel = infrastructure()
    voided_per_unit_of_work: Counter[SessionProvider] = Counter()

    async def count_voided(_: InvoiceVoided) -> None:
        voided_per_unit_of_work[current_session_provider()] += 1

    kernel.event_bus.subscribe(InvoiceVoided, count_voided)
    configure(
        session_factory=kernel.session_factory,
        event_bus=kernel.event_bus,
        publisher=kernel.publisher,
        task_queue=kernel.task_queue,
        max_events_per_unit_of_work=150,
    )
    customer = uuid4()
    invoices = await invoices_of(session_factory, organization_id, customer, count=250)
    message = envelope(organization_id, {"customerId": str(customer)})

    await send(broker, message)
    await send(broker, message)
    await processed_once(session_factory)

    assert await statuses(session_factory, organization_id, invoices) == {
        InvoiceStatus.ACTIVE.value
    }
    assert [job[0] for job in await jobs(session_factory)] == [VOID_INVOICES] * 3
    assert not voided_per_unit_of_work

    await drain(connection, session_factory)

    assert await statuses(session_factory, organization_id, invoices) == {
        InvoiceStatus.VOIDED.value
    }
    assert await dead_letters(amqp_url) == []
    assert await processed(session_factory) == 1
    async with session_factory() as session:
        voided_events = await session.scalar(
            select(func.count())
            .select_from(DomainEventModel)
            .where(DomainEventModel.name == "InvoiceVoided")
        )
    assert voided_events == 250
    assert len(voided_per_unit_of_work) == 3
    assert max(voided_per_unit_of_work.values()) <= BULK_CHUNK_SIZE


async def test_unusable_messages_go_to_the_dead_letter_queue(
    broker: RabbitBroker, amqp_url: str, session_factory: Factory, organization_id: UUID
) -> None:
    await send(broker, envelope(organization_id, {}))
    missing_organization = envelope(organization_id, {"customerId": str(uuid4())})
    del missing_organization["organizationId"]
    await send(broker, missing_organization)
    await send(broker, envelope(None, {"customerId": str(uuid4())}))

    bodies: list[dict[str, Any]] = []

    async def collected() -> bool:
        bodies.extend(await dead_letters(amqp_url))
        return len(bodies) >= 2

    await eventually(collected)
    await asyncio.sleep(0.5)

    assert sorted(len(body["data"]) for body in [*bodies, *await dead_letters(amqp_url)]) == [0, 1]
    assert await processed(session_factory) == 0


async def test_api_lifespan_connects_the_publisher(
    amqp_url: str, database_url: str, tokens: TokenFactory
) -> None:
    settings = Settings(
        service_name="example-tests",
        database_url=database_url,
        rabbitmq_url=amqp_url,
        jwt=tokens.settings,
        notification_url="https://notification.test",
    )
    runtime = build_runtime(settings, role="api")
    app = build_app(runtime, tokens.verifier())

    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
            ready = await http.get("/health/ready")
        assert await runtime.broker.ping(timeout=5)

    assert ready.status_code == 200
