import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Generator
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar, cast
from uuid import UUID, uuid4

import aio_pika
import pytest
from aio_pika.abc import AbstractIncomingMessage
from faststream.rabbit import RabbitBroker
from opentelemetry.trace import SpanKind
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from fast_ddd.context import (
    ContextNotSetError,
    User,
    current_organization_id,
    current_parent_event_id,
    current_trace_id,
)
from fast_ddd.errors import AggregateNotFound, DomainError, ErrorKind, LockConflict
from fast_ddd.event_bus import EventBus
from fast_ddd.events import DomainEvent
from fast_ddd_adapter.controller import execute
from fast_ddd_adapter.infrastructure import configure
from fast_ddd_adapter.messaging import (
    FastStreamPublisher,
    create_broker,
    integration_message,
    publish_after_commit,
)
from fast_ddd_adapter.orm import ProcessedMessage
from fast_ddd_adapter.repository import domain_event_row
from fast_ddd_adapter.testing import unit_of_work_scope
from fast_ddd_port.models import MessageModel, Timestamp
from fast_ddd_port.subscriber import (
    Envelope,
    declare_dead_letter_queue,
    kernel_queue,
    subscribe,
)
from tests.adapter.models import OrderCreated, OrderModel, OrderRepository
from tests.adapter.use_cases import OrderUseCase
from tests.telemetry import Telemetry, span_trace_id

EXCHANGE = "kernel-test-events"
QUEUE = "kernel-test.order-created"


class OrderCreatedData(MessageModel):
    code: str


class TimestampData(MessageModel):
    payload_timestamp: Timestamp


@dataclass
class RejectedCode(DomainError):
    code: ClassVar[str] = "kernel_test.message.rejected"
    kind: ClassVar[ErrorKind] = ErrorKind.INVALID
    message: ClassVar[str] = "rejected"


@dataclass
class Seen:
    calls: list[tuple[str, UUID | None, UUID | None]]
    trace_ids: list[str | None]


@pytest.fixture(scope="session")
def rabbitmq() -> Generator[DockerContainer]:
    container = (
        DockerContainer("rabbitmq:4-management")
        .with_exposed_ports(5672)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def amqp_url(rabbitmq: DockerContainer) -> str:
    host = rabbitmq.get_container_host_ip()
    port = rabbitmq.get_exposed_port(5672)
    return f"amqp://guest:guest@{host}:{port}/"


@pytest.fixture
async def broker(
    amqp_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncGenerator[tuple[RabbitBroker, Seen]]:
    seen = Seen(calls=[], trace_ids=[])
    broker = create_broker(amqp_url)

    async def handle(envelope: Envelope, data: OrderCreatedData) -> None:
        seen.calls.append((data.code, current_organization_id(), current_parent_event_id()))
        seen.trace_ids.append(current_trace_id())
        if data.code == "not-found":
            raise AggregateNotFound(
                namespace="kernel_test.order", aggregate_type="order", aggregate_id=uuid4()
            )
        if data.code == "invalid":
            raise RejectedCode()
        if data.code == "locked":
            raise LockConflict()
        if data.code == "crash":
            raise RuntimeError("handler crashed")
        if data.code == "write-then-reject":
            organization_id = envelope.organization_id or uuid4()
            await execute(
                lambda: OrderUseCase(OrderRepository()).create(uuid4(), organization_id, "w")
            )
            raise RejectedCode()

    subscribe(
        broker,
        name="order-created-test",
        queue=kernel_queue(QUEUE, routing_key="OrderCreated"),
        max_retries=2,
        exchange=EXCHANGE,
        payload=OrderCreatedData,
        handler=handle,
        session_factory=session_factory,
    )
    await broker.start()
    await declare_dead_letter_queue(broker, QUEUE)
    configure(
        session_factory=session_factory,
        event_bus=EventBus(),
        publisher=FastStreamPublisher(broker),
    )
    yield broker, seen
    await broker.stop()


def envelope(
    code: str, organization_id: UUID | None, event_id: UUID | None = None
) -> dict[str, Any]:
    return {
        "eventId": str(event_id or uuid4()),
        "eventName": "OrderCreated",
        "eventVersion": 1,
        "organizationId": str(organization_id) if organization_id else None,
        "occurredAt": "2026-10-18T00:00:00.000Z",
        "data": {"code": code},
    }


async def send(broker: RabbitBroker, body: dict[str, Any]) -> None:
    await broker.publish(body, exchange=EXCHANGE, routing_key="OrderCreated")


async def eventually(condition: Callable[[], bool], within: float = 10.0) -> None:
    for _ in range(int(within / 0.05)):
        if condition():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("condition not met")


async def dead_letters(amqp_url: str) -> list[dict[str, Any]]:
    connection = await aio_pika.connect(amqp_url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.get_queue(f"{QUEUE}.dlq", ensure=False)
        bodies: list[dict[str, Any]] = []
        while (message := await queue.get(no_ack=True, fail=False)) is not None:
            import json

            bodies.append(json.loads(message.body))
        return bodies


async def count(factory: async_sessionmaker[AsyncSession], model: type[Any]) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_message_is_processed_once_with_event_context(
    broker: tuple[RabbitBroker, Seen],
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> None:
    rabbit, seen = broker
    event_id = uuid4()
    await send(rabbit, envelope("ok", organization_id, event_id))
    await send(rabbit, envelope("ok", organization_id, event_id))
    await eventually(lambda: len(seen.calls) >= 1)
    await asyncio.sleep(0.5)

    assert seen.calls == [("ok", organization_id, event_id)]
    assert await count(session_factory, ProcessedMessage) == 1


@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"])
@pytest.mark.parametrize("field", ["occurredAt", "payloadTimestamp"])
async def test_out_of_range_timestamps_reach_dlq_before_inbox_or_handler(
    amqp_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
    timestamp: str,
    field: str,
) -> None:
    queue_name = f"timestamp-{uuid4().hex}"
    rabbit = create_broker(amqp_url)
    calls: list[TimestampData] = []

    async def handle(_: Envelope, data: TimestampData) -> None:
        calls.append(data)

    subscribe(
        rabbit,
        name=queue_name,
        queue=kernel_queue(queue_name, routing_key=queue_name),
        exchange=EXCHANGE,
        payload=TimestampData,
        handler=handle,
        session_factory=session_factory,
    )
    await rabbit.start()
    try:
        await declare_dead_letter_queue(rabbit, queue_name)
        body = envelope("time", organization_id)
        body["data"] = {"payloadTimestamp": "2026-10-18T00:00:00Z"}
        if field == "occurredAt":
            body[field] = timestamp
        else:
            body["data"][field] = timestamp
        await rabbit.publish(body, exchange=EXCHANGE, routing_key=queue_name)
        connection = await aio_pika.connect(amqp_url)
        async with connection:
            channel = await connection.channel()
            queue = await channel.get_queue(f"{queue_name}.dlq", ensure=False)
            message = None
            for _ in range(40):
                message = await queue.get(no_ack=True, fail=False)
                if message is not None:
                    break
                await asyncio.sleep(0.05)
            assert calls == []
            assert await count(session_factory, ProcessedMessage) == 0
            assert message is not None
            assert json.loads(message.body) == body
            deaths = cast(list[dict[str, Any]], message.headers["x-death"])
            assert deaths[0]["reason"] == "rejected"
            assert await queue.get(no_ack=True, fail=False) is None
    finally:
        await rabbit.stop()


def outcomes(telemetry: Telemetry) -> dict[str, float]:
    return {
        outcome: telemetry.total(
            "fast_ddd.mq.consume.duration", subscriber="order-created-test", outcome=outcome
        )
        for outcome in ("success", "skipped", "requeued", "dead_lettered")
    }


async def test_rejections_route_by_kind(
    broker: tuple[RabbitBroker, Seen],
    amqp_url: str,
    organization_id: UUID,
    telemetry: Telemetry,
) -> None:
    rabbit, seen = broker
    await dead_letters(amqp_url)
    before = outcomes(telemetry)
    await send(rabbit, envelope("not-found", organization_id))
    await send(rabbit, envelope("invalid", organization_id))
    await send(rabbit, {"eventId": str(uuid4()), "data": {}})
    await send(rabbit, envelope("global", None))
    await eventually(lambda: len(seen.calls) >= 2)
    await asyncio.sleep(1.0)

    codes = sorted(
        body.get("data", {}).get("code", "malformed") for body in await dead_letters(amqp_url)
    )
    assert codes == ["invalid", "malformed"]
    assert sorted(code for code, _, _ in seen.calls) == ["invalid", "not-found"]
    after = outcomes(telemetry)
    assert {k: after[k] - before[k] for k in after} == {
        "success": 0,
        "skipped": 2,
        "requeued": 0,
        "dead_lettered": 2,
    }


async def test_crashing_handler_is_retried_then_dead_lettered(
    broker: tuple[RabbitBroker, Seen], amqp_url: str, organization_id: UUID
) -> None:
    rabbit, seen = broker
    await dead_letters(amqp_url)
    await send(rabbit, envelope("crash", organization_id))
    await eventually(lambda: len(seen.calls) >= 3, within=20.0)
    await asyncio.sleep(1.5)

    assert [body["data"]["code"] for body in await dead_letters(amqp_url)] == ["crash"]
    assert len(seen.calls) == 3


async def test_domain_error_after_write_rolls_back_write_and_inbox(
    broker: tuple[RabbitBroker, Seen],
    amqp_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> None:
    rabbit, seen = broker
    await dead_letters(amqp_url)
    await send(rabbit, envelope("write-then-reject", organization_id))
    await eventually(lambda: len(seen.calls) >= 1)
    await asyncio.sleep(0.5)

    assert await count(session_factory, OrderModel) == 0
    assert await count(session_factory, ProcessedMessage) == 0


async def test_publish_after_commit_sends_only_committed_events(
    broker: tuple[RabbitBroker, Seen],
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> None:
    rabbit, seen = broker
    doer = User(id="publisher")
    bus = EventBus()

    async def forward(event: OrderCreated) -> None:
        publish_after_commit(integration_message(event, exchange=EXCHANGE))

    bus.subscribe(OrderCreated, forward)
    configure(session_factory=session_factory, event_bus=bus, publisher=FastStreamPublisher(rabbit))

    with unit_of_work_scope(session_factory, user=doer, organization_id=organization_id):
        await execute(
            lambda: OrderUseCase(OrderRepository()).create(uuid4(), organization_id, "ok")
        )

    async def create_then_fail() -> None:
        await OrderUseCase(OrderRepository()).create(uuid4(), organization_id, "rolled-back")
        raise ZeroDivisionError

    with (
        unit_of_work_scope(session_factory, user=doer, organization_id=organization_id),
        pytest.raises(ZeroDivisionError),
    ):
        await execute(create_then_fail)

    await eventually(lambda: len(seen.calls) >= 1)
    await asyncio.sleep(0.5)
    assert [code for code, _, _ in seen.calls] == ["ok"]


async def test_consumer_continues_the_publishers_trace(
    broker: tuple[RabbitBroker, Seen],
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
    telemetry: Telemetry,
) -> None:
    rabbit, seen = broker
    bus = EventBus()

    async def forward(event: OrderCreated) -> None:
        publish_after_commit(integration_message(event, exchange=EXCHANGE))

    bus.subscribe(OrderCreated, forward)
    configure(session_factory=session_factory, event_bus=bus, publisher=FastStreamPublisher(rabbit))

    with (
        span_trace_id("request") as trace_id,
        unit_of_work_scope(
            session_factory,
            user=User(id="publisher"),
            organization_id=organization_id,
            trace_id=trace_id,
        ),
    ):
        await execute(
            lambda: OrderUseCase(OrderRepository()).create(uuid4(), organization_id, "ok")
        )
    await eventually(lambda: len(seen.calls) >= 1)
    await asyncio.sleep(0.2)

    assert seen.trace_ids == [trace_id]
    kinds = {span.kind for span in telemetry.spans(trace_id)}
    assert {SpanKind.PRODUCER, SpanKind.CONSUMER} <= kinds


@dataclass(frozen=True)
class DeliveryAddress:
    postal_code: str


class DeliveryStatus(StrEnum):
    READY = "ready"


@dataclass(frozen=True, kw_only=True)
class DeliveryCreated(DomainEvent):
    customer_id: UUID
    shipping_address: DeliveryAddress
    custom_labels: dict[str, str]
    total_amount: Decimal
    delivery_status: DeliveryStatus = DeliveryStatus.READY


class DeliveryAddressData(MessageModel):
    postal_code: str


class DeliveryData(MessageModel):
    customer_id: UUID
    shipping_address: DeliveryAddressData
    custom_labels: dict[str, str]
    total_amount: Decimal
    delivery_status: DeliveryStatus


def delivery(organization_id: UUID | None) -> DeliveryCreated:
    return DeliveryCreated(
        doer=User(id="producer"),
        organization_id=organization_id,
        customer_id=uuid4(),
        shipping_address=DeliveryAddress("100"),
        custom_labels={"do_not_change": "yes"},
        total_amount=Decimal("12.30"),
    )


def test_integration_message_preserves_typed_fields_before_serializing() -> None:
    event = delivery(uuid4())
    message = integration_message(event, exchange=EXCHANGE)
    assert message.body["data"] == {
        "customerId": str(event.customer_id),
        "shippingAddress": {"postalCode": "100"},
        "customLabels": {"do_not_change": "yes"},
        "totalAmount": "12.30",
        "deliveryStatus": "ready",
    }
    assert domain_event_row(event).body == {
        "customer_id": str(event.customer_id),
        "shipping_address": {"postal_code": "100"},
        "custom_labels": {"do_not_change": "yes"},
        "total_amount": "12.30",
        "delivery_status": "ready",
    }
    assert set(message.body) == {
        "eventId",
        "eventName",
        "eventVersion",
        "organizationId",
        "occurredAt",
        "data",
    }


@pytest.mark.parametrize("global_first", [False, True])
async def test_real_producer_consumer_contract_accepts_unknown_and_global_fields(
    amqp_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    global_first: bool,
) -> None:
    rabbit = create_broker(amqp_url)
    seen: list[tuple[Envelope, DeliveryData]] = []
    global_observed = asyncio.Event()
    queue_name = f"kernel-test.contract-{uuid4()}"

    async def handle(envelope: Envelope, data: DeliveryData) -> None:
        if global_first and envelope.organization_id is not None:
            async with asyncio.timeout(5):
                await global_observed.wait()
        seen.append((envelope, data))
        if envelope.organization_id is None:
            global_observed.set()

    subscribe(
        rabbit,
        name=queue_name,
        queue=kernel_queue(queue_name, routing_key="DeliveryCreated"),
        exchange=EXCHANGE,
        payload=DeliveryData,
        handler=handle,
        session_factory=session_factory,
        accepts_global=True,
    )
    await rabbit.start()
    try:
        publisher = FastStreamPublisher(rabbit)
        events = [delivery(uuid4()), delivery(None)]
        for event in events:
            message = integration_message(event, exchange=EXCHANGE)
            message.body["futureEnvelopeField"] = "ignored"
            data = message.body["data"]
            assert isinstance(data, dict)
            data["futurePayloadField"] = "ignored"
            await publisher.publish(message)
        await eventually(lambda: len(seen) == 2)
        assert len(seen) == len(events)
        seen_by_id = {envelope.event_id: (envelope, data) for envelope, data in seen}
        assert set(seen_by_id) == {event.event_id for event in events}
        for event in events:
            envelope, data = seen_by_id[event.event_id]
            assert envelope.organization_id == event.organization_id
            assert data.customer_id == event.customer_id
            assert data.shipping_address.postal_code == "100"
            assert data.custom_labels == {"do_not_change": "yes"}
            assert data.total_amount == Decimal("12.30")
            assert data.delivery_status == DeliveryStatus.READY
    finally:
        await rabbit.stop()


async def test_concurrent_consumers_keep_organization_parent_and_trace_context_isolated(
    amqp_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    rabbits = [create_broker(amqp_url), create_broker(amqp_url)]
    entered = 0
    both_entered = asyncio.Event()
    done = asyncio.Event()
    observed: list[tuple[UUID | None, UUID | None, str | None]] = []
    expected: list[tuple[UUID | None, UUID | None, str | None]] = []

    async def handle(_envelope: Envelope, _: OrderCreatedData) -> None:
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        async with asyncio.timeout(5):
            await both_entered.wait()
        observed.append((current_organization_id(), current_parent_event_id(), current_trace_id()))
        if len(observed) == 2:
            done.set()

    try:
        for index, rabbit in enumerate(rabbits):
            route = f"Concurrent-{uuid4()}"
            name = f"kernel-test.context-{uuid4()}"
            subscribe(
                rabbit,
                name=name,
                queue=kernel_queue(name, routing_key=route),
                exchange=EXCHANGE,
                payload=OrderCreatedData,
                handler=handle,
                session_factory=session_factory,
            )
            await rabbit.start()
            org, event_id, trace = uuid4(), uuid4(), f"context-{index}"
            expected.append((org, event_id, trace))
            await rabbit.publish(
                envelope("ok", org, event_id),
                exchange=EXCHANGE,
                routing_key=route,
                headers={"trace-id": trace},
            )
        async with asyncio.timeout(10):
            await done.wait()
        assert set(observed) == set(expected)
        with pytest.raises(ContextNotSetError):
            current_organization_id()
        assert current_parent_event_id() is None
    finally:
        for rabbit in rabbits:
            await rabbit.stop()


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        ([], None),
        ("not-json", None),
        (b"{", "application/json"),
        (b"42", "application/json"),
        (b"null", "application/json"),
        (b'"text"', "application/json"),
        (b"true", "application/json"),
    ],
)
async def test_invalid_json_and_non_object_roots_are_dead_lettered(
    broker: tuple[RabbitBroker, Seen],
    amqp_url: str,
    organization_id: UUID,
    telemetry: Telemetry,
    body: Any,
    content_type: str | None,
) -> None:
    rabbit, seen = broker
    await dead_letters(amqp_url)
    before = outcomes(telemetry)
    await rabbit.publish(
        body, content_type=content_type, exchange=EXCHANGE, routing_key="OrderCreated"
    )
    connection = await aio_pika.connect(amqp_url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.get_queue(f"{QUEUE}.dlq", ensure=False)
        received = None
        for _ in range(40):
            received = await queue.get(no_ack=True, fail=False)
            if received is not None:
                break
            await asyncio.sleep(0.05)
        assert received is not None, "invalid input must reach DLQ while consumer stays alive"
        deaths = cast(list[dict[str, Any]], received.headers["x-death"])
        assert deaths[0]["reason"] == "rejected"
    assert seen.calls == []
    assert outcomes(telemetry)["dead_lettered"] - before["dead_lettered"] == 1
    assert outcomes(telemetry)["requeued"] == before["requeued"]
    event_id = uuid4()
    await send(rabbit, envelope("healthy", organization_id, event_id))
    await eventually(lambda: len(seen.calls) == 1)
    assert seen.calls == [("healthy", organization_id, event_id)]


async def next_dead_letter(amqp_url: str) -> AbstractIncomingMessage:
    connection = await aio_pika.connect(amqp_url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.get_queue(f"{QUEUE}.dlq", ensure=False)
        for _ in range(60):
            message = await queue.get(no_ack=True, fail=False)
            if message is not None:
                return message
            await asyncio.sleep(0.05)
        raise TimeoutError("message did not reach DLQ")


@pytest.mark.parametrize(
    "retry_count",
    [
        pytest.param("invalid", id="noninteger"),
        pytest.param(-1, id="negative-integer"),
        pytest.param("-1", id="negative-string"),
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param(1.0, id="integral-float"),
        pytest.param(1.5, id="fractional-float"),
        pytest.param(bytearray(b"1"), id="bytes"),
        pytest.param(None, id="null"),
        pytest.param("9" * 4301, id="oversized-digits"),
        pytest.param([], id="list"),
        pytest.param({}, id="mapping"),
    ],
)
async def test_invalid_retry_metadata_is_dead_lettered_before_handler_or_inbox(
    broker: tuple[RabbitBroker, Seen],
    amqp_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
    telemetry: Telemetry,
    retry_count: Any,
) -> None:
    rabbit, seen = broker
    await dead_letters(amqp_url)
    before = outcomes(telemetry)
    body = json.dumps(envelope("crash", organization_id)).encode()
    await rabbit.publish(
        body,
        content_type="application/json",
        exchange=EXCHANGE,
        routing_key="OrderCreated",
        headers={"x-retry-count": retry_count, "custom-header": "preserved"},
    )
    received = await next_dead_letter(amqp_url)
    assert received.body == body
    assert received.headers["x-retry-count"] == retry_count
    assert received.headers["custom-header"] == "preserved"
    deaths = cast(list[dict[str, Any]], received.headers["x-death"])
    assert deaths[0]["reason"] == "rejected"
    assert seen.calls == []
    assert await count(session_factory, ProcessedMessage) == 0
    assert outcomes(telemetry)["dead_lettered"] - before["dead_lettered"] == 1
    assert outcomes(telemetry)["requeued"] == before["requeued"]
    event_id = uuid4()
    await send(rabbit, envelope("healthy", organization_id, event_id))
    await eventually(lambda: len(seen.calls) == 1)
    assert seen.calls == [("healthy", organization_id, event_id)]


@pytest.mark.parametrize("code", ["crash", "locked"])
@pytest.mark.parametrize(
    ("headers", "initial_count"),
    [
        pytest.param({}, 0, id="missing"),
        pytest.param({"x-retry-count": 0}, 0, id="zero"),
        pytest.param({"x-retry-count": 1}, 1, id="positive"),
        pytest.param({"x-retry-count": "0"}, 0, id="string-zero"),
        pytest.param({"x-retry-count": "1"}, 1, id="string-positive"),
        pytest.param({"x-retry-count": "01"}, 1, id="leading-zero"),
        pytest.param({"x-retry-count": "+1"}, 1, id="explicit-positive"),
        pytest.param({"x-retry-count": " 1 "}, 1, id="whitespace"),
        pytest.param({"x-retry-count": 2}, 2, id="retry-limit"),
        pytest.param({"x-retry-count": 3}, 3, id="exhausted"),
        pytest.param({"x-retry-count": 2**63 - 1}, 2**63 - 1, id="max-amqp-integer"),
    ],
)
async def test_valid_retry_metadata_preserves_finite_retry_budget(
    broker: tuple[RabbitBroker, Seen],
    amqp_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
    telemetry: Telemetry,
    code: str,
    headers: dict[str, Any],
    initial_count: int,
) -> None:
    rabbit, seen = broker
    await dead_letters(amqp_url)
    before = outcomes(telemetry)
    event_id = uuid4()
    body = json.dumps(envelope(code, organization_id, event_id)).encode()
    await rabbit.publish(
        body,
        content_type="application/json",
        exchange=EXCHANGE,
        routing_key="OrderCreated",
        headers={**headers, "custom-header": "preserved"},
    )
    received = await next_dead_letter(amqp_url)
    retries = max(0, 2 - initial_count)
    assert received.body == body
    assert received.headers["custom-header"] == "preserved"
    assert received.headers["x-retry-count"] == max(initial_count, 2)
    assert seen.calls == [(code, organization_id, event_id)] * (retries + 1)
    assert await count(session_factory, ProcessedMessage) == 0
    assert outcomes(telemetry)["dead_lettered"] - before["dead_lettered"] == 1
    assert outcomes(telemetry)["requeued"] - before["requeued"] == retries
