"""Service-owned wiring: what this service registers into the kernel's composition root."""

from collections.abc import Awaitable, Callable

from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.http_client import create_http_client
from fast_ddd_port.tasks import TaskRegistry
from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapter.event_handler.billing import invoice_event_handler
from app.adapter.notification.notification_client import NotificationClient
from app.adapter.resources import Resources, configure_resources
from app.port.message_queue.customer import customer_subscriber
from app.port.restful.billing import invoice_router
from app.port.task.billing import invoice_tasks
from app.settings import Settings

type Closer = Callable[[], Awaitable[None]]


def wire_resources(settings: Settings) -> list[Closer]:
    """Build service-owned infrastructure; returns what must be closed at shutdown."""
    notification_http = create_http_client(
        "notification",
        base_url=settings.notification_url,
        timeout=settings.notification_timeout_seconds,
    )
    configure_resources(Resources(notification=NotificationClient(notification_http)))
    return [notification_http.aclose]


def wire_events(bus: EventBus) -> None:
    invoice_event_handler.register(bus)


def wire_http(app: FastAPI) -> None:
    app.include_router(invoice_router.router)


def wire_consumer(
    broker: RabbitBroker, session_factory: async_sessionmaker[AsyncSession]
) -> list[str]:
    """Register subscribers (consumer process only); returns queue names needing a DLQ."""
    return customer_subscriber.register(broker, session_factory)


def wire_tasks(registry: TaskRegistry) -> None:
    invoice_tasks.register(registry)
