"""Composition root shared by the API, the MQ consumer and the task worker."""

from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.infrastructure import configure, create_engine, create_session_factory
from fast_ddd_adapter.messaging import FastStreamPublisher, create_broker
from fast_ddd_adapter.observability import Telemetry, configure_logging, setup_telemetry
from fast_ddd_adapter.tasks import PgQueuerTaskQueue
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.settings import Settings
from app.wiring import Closer, wire_events, wire_resources


@dataclass(slots=True)
class Runtime:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    broker: RabbitBroker
    closers: list[Closer] = field(default_factory=list[Closer])

    async def close(self) -> None:
        async with AsyncExitStack() as stack:
            stack.push_async_callback(self.engine.dispose)
            for close in self.closers:
                stack.push_async_callback(close)


def configure_process(settings: Settings) -> Telemetry:
    """Configure logging and OpenTelemetry once; the caller owns shutdown."""
    configure_logging(settings.log_level)
    return setup_telemetry(settings.service_name, settings.telemetry_exporter)


def build_runtime(settings: Settings, *, role: str) -> Runtime:
    if settings.rabbitmq_url is None:
        raise ValueError("RABBITMQ_URL is required")
    engine = create_engine(
        settings.database_url,
        application_name=f"{settings.service_name}:{role}",
        lock_timeout_ms=settings.lock_timeout_ms,
        statement_timeout_ms=settings.statement_timeout_ms,
        idle_in_transaction_session_timeout_ms=settings.idle_in_transaction_session_timeout_ms,
    )
    session_factory = create_session_factory(engine)
    broker = create_broker(settings.rabbitmq_url)
    bus = EventBus()
    configure(
        session_factory=session_factory,
        event_bus=bus,
        publisher=FastStreamPublisher(broker),
        task_queue=PgQueuerTaskQueue(),
    )
    closers = wire_resources(settings)
    wire_events(bus)
    return Runtime(settings, engine, session_factory, broker, closers)
