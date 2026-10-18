from collections.abc import Awaitable, Callable

from fast_ddd.event_bus import EventBus
from fast_ddd_port.tasks import TaskRegistry
from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.settings import Settings

type Closer = Callable[[], Awaitable[None]]


def wire_resources(_settings: Settings) -> list[Closer]:
    return []


def wire_events(_bus: EventBus) -> None:
    pass


def wire_http(_app: FastAPI) -> None:
    pass


def wire_consumer(
    _broker: RabbitBroker, _session_factory: async_sessionmaker[AsyncSession]
) -> list[str]:
    return []


def wire_tasks(_registry: TaskRegistry) -> None:
    pass
