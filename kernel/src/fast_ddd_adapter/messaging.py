import dataclasses
import logging
from typing import Any
from uuid import UUID

import pendulum
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange
from faststream.rabbit.opentelemetry import RabbitTelemetryMiddleware
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from fast_ddd.events import DomainEvent
from fast_ddd.serialization import format_datetime, to_json
from fast_ddd_adapter.infrastructure import NotConfiguredError, OutgoingMessage, infrastructure
from fast_ddd_adapter.orm import ProcessedMessage
from fast_ddd_adapter.session import current_session_provider

_EVENT_BASE_FIELDS = frozenset(f.name for f in dataclasses.fields(DomainEvent))


def create_broker(url: str) -> RabbitBroker:
    """Broker with W3C trace context propagation and publish/consume metrics."""
    return RabbitBroker(
        url,
        logger=logging.getLogger("faststream.kernel.rabbit"),
        middlewares=(RabbitTelemetryMiddleware(include_messages_counters=True),),
    )


def event_exchange(name: str) -> RabbitExchange:
    return RabbitExchange(name, type=ExchangeType.TOPIC, durable=True)


def integration_message(
    event: DomainEvent, *, exchange: str, routing_key: str | None = None
) -> OutgoingMessage:
    """The cross-service envelope; ``organizationId`` comes from the event's aggregate."""
    body = {
        "eventId": str(event.event_id),
        "eventName": event.name,
        "eventVersion": event.VERSION,
        "organizationId": str(event.organization_id) if event.organization_id else None,
        "occurredAt": format_datetime(event.occurred_at),
        "data": to_json(event, camel_case=True, exclude_fields=_EVENT_BASE_FIELDS),
    }
    headers = {"trace-id": event.trace_id} if event.trace_id else {}
    return OutgoingMessage(
        exchange=exchange,
        routing_key=routing_key or event.name,
        body=body,
        headers=headers,
    )


def publish_after_commit(message: OutgoingMessage) -> None:
    """Stage a message; it is sent only after the outermost transaction commits."""
    publisher = infrastructure().publisher
    if publisher is None:
        raise NotConfiguredError("no publisher configured; pass one to configure()")
    current_session_provider().after_commit(lambda: publisher.publish(message))


class FastStreamPublisher:
    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    async def publish(self, message: OutgoingMessage) -> None:
        headers: dict[str, Any] = dict(message.headers)
        await self._broker.publish(
            message.body,
            exchange=event_exchange(message.exchange),
            routing_key=message.routing_key,
            headers=headers,
            persist=True,
        )


async def claim_message(session: AsyncSession, subscriber: str, event_id: UUID) -> bool:
    """Record the event for this subscriber; False when it was already processed."""
    statement = (
        insert(ProcessedMessage)
        .values(subscriber=subscriber, event_id=event_id, processed_at=pendulum.now("UTC"))
        .on_conflict_do_nothing()
        .returning(ProcessedMessage.event_id)
    )
    inserted = (await session.execute(statement)).scalar_one_or_none()
    return inserted is not None


async def is_processed(session: AsyncSession, subscriber: str, event_id: UUID) -> bool:
    statement = select(ProcessedMessage.event_id).where(
        ProcessedMessage.subscriber == subscriber, ProcessedMessage.event_id == event_id
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None
