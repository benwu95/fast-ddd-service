import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import UUID

from faststream import AckPolicy
from faststream.rabbit import (
    ExchangeType,
    QueueType,
    RabbitBroker,
    RabbitExchange,
    RabbitQueue,
)
from faststream.rabbit.annotations import RabbitMessage
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd.context import User, unit_of_work_context
from fast_ddd.errors import DomainError, ErrorKind, LockConflict
from fast_ddd_adapter.messaging import claim_message, event_exchange
from fast_ddd_adapter.observability import meter, resolve_trace_id
from fast_ddd_adapter.session import SessionProvider, session_provider_scope
from fast_ddd_port.models import MessageModel, Timestamp

logger = logging.getLogger(__name__)

DEAD_LETTER_EXCHANGE = "dead-letter"
RETRY_HEADER = "x-retry-count"

type Outcome = Literal["success", "skipped", "requeued", "dead_lettered"]

_consume_duration = meter.create_histogram(
    "fast_ddd.mq.consume.duration",
    unit="s",
    description="Messages handled by kernel subscribers, by subscriber and outcome",
)


class Envelope(MessageModel):
    """The cross-service message wrapper; ``organizationId`` must be present (may be null)."""

    event_id: UUID
    event_name: str
    event_version: int
    organization_id: UUID | None
    occurred_at: Timestamp
    data: dict[str, Any]


def kernel_queue(name: str, *, routing_key: str, delivery_limit: int = 10) -> RabbitQueue:
    """Quorum queue that dead-letters rejected messages to ``<name>.dlq``.

    ``delivery_limit`` only catches consumers that die mid-message: RabbitMQ 4 does not count
    explicit requeues, so handler retries are counted by the wrapper (``max_retries``).
    """
    return RabbitQueue(
        name,
        queue_type=QueueType.QUORUM,
        durable=True,
        routing_key=routing_key,
        arguments={
            "x-delivery-limit": delivery_limit,
            "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
            "x-dead-letter-routing-key": f"{name}.dlq",
        },
    )


async def declare_dead_letter_queue(broker: RabbitBroker, queue_name: str) -> None:
    exchange = await broker.declare_exchange(
        RabbitExchange(DEAD_LETTER_EXCHANGE, type=ExchangeType.DIRECT, durable=True)
    )
    dead_letters = await broker.declare_queue(
        RabbitQueue(f"{queue_name}.dlq", queue_type=QueueType.QUORUM, durable=True)
    )
    await dead_letters.bind(exchange, routing_key=f"{queue_name}.dlq")


def subscribe[T: MessageModel](
    broker: RabbitBroker,
    *,
    name: str,
    queue: RabbitQueue,
    exchange: str,
    payload: type[T],
    handler: Callable[[Envelope, T], Awaitable[None]],
    session_factory: async_sessionmaker[AsyncSession],
    accepts_global: bool = False,
    max_retries: int = 3,
) -> None:
    """Register ``handler`` behind the kernel wrapper: context, inbox, transaction and ack.

    Deterministic rejections (validation, INVALID) go to the DLQ; NOT_FOUND/CONFLICT-like
    rejections are acked and skipped; lock conflicts and unexpected errors are retried
    ``max_retries`` times, then dead-lettered.
    """
    consumer = User(id=f"consumer:{name}")

    async def retry_or_dead_letter(message: RabbitMessage, retry_count: int) -> Outcome:
        attempt = retry_count + 1
        if attempt > max_retries:
            await message.reject(requeue=False)
            return "dead_lettered"
        headers: dict[str, Any] = {**message.headers, RETRY_HEADER: attempt}
        await broker.publish(
            message.body,
            queue=queue.name,
            headers=headers,
            content_type=message.content_type,
            persist=True,
        )
        await message.ack()
        return "requeued"

    async def handle(body: bytes, message: RabbitMessage) -> Outcome:
        try:
            envelope = Envelope.model_validate_json(body)
            data = payload.model_validate(envelope.data)
            retry_header = message.headers.get(RETRY_HEADER, 0)
            if isinstance(retry_header, bool) or not isinstance(retry_header, (int, str)):
                raise ValueError("retry count must be a nonnegative integer")
            retry_count = int(retry_header)
            if retry_count < 0:
                raise ValueError("retry count must be a nonnegative integer")
        except (ValidationError, ValueError):
            logger.warning("rejecting malformed message on %s", name, exc_info=True)
            await message.reject(requeue=False)
            return "dead_lettered"
        if envelope.organization_id is None and not accepts_global:
            await message.ack()
            return "skipped"
        provider = SessionProvider(session_factory)
        try:
            with (
                unit_of_work_context(
                    user=consumer,
                    organization_id=envelope.organization_id,
                    trace_id=resolve_trace_id(message.headers.get("trace-id")),
                    parent_event_id=envelope.event_id,
                ),
                session_provider_scope(provider),
            ):
                async with provider:
                    claimed = await claim_message(provider.session, name, envelope.event_id)
                    if claimed:
                        await handler(envelope, data)
        except LockConflict:
            return await retry_or_dead_letter(message, retry_count)
        except DomainError as error:
            if error.kind is ErrorKind.INVALID:
                logger.warning("dead-lettering %s: %s", envelope.event_id, error.error_code)
                await message.reject(requeue=False)
                return "dead_lettered"
            logger.warning("skipping %s: %s", envelope.event_id, error.error_code)
            await message.ack()
            return "skipped"
        except Exception:
            logger.exception("handler %s failed for %s", name, envelope.event_id)
            return await retry_or_dead_letter(message, retry_count)
        await message.ack()
        return "success" if claimed else "skipped"

    async def raw_body(message: RabbitMessage) -> bytes:
        return message.body

    async def consume(body: bytes, message: RabbitMessage) -> None:
        started = time.perf_counter()
        outcome = await handle(body, message)
        _consume_duration.record(
            time.perf_counter() - started, {"subscriber": name, "outcome": outcome}
        )

    broker.subscriber(
        queue, event_exchange(exchange), ack_policy=AckPolicy.MANUAL, decoder=raw_body
    )(consume)
