import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fast_ddd.context import tenant_exemption
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.observability import instrument_engine
from fast_ddd_adapter.tasks import TaskQueue

logger = logging.getLogger(__name__)


class NotConfiguredError(RuntimeError):
    pass


class Publisher(Protocol):
    async def publish(self, message: "OutgoingMessage") -> None: ...


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    exchange: str
    routing_key: str
    body: dict[str, Any]
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class KernelInfrastructure:
    session_factory: async_sessionmaker[AsyncSession]
    event_bus: EventBus
    publisher: Publisher | None = None
    task_queue: TaskQueue | None = None
    max_event_chain_depth: int = 10
    max_events_per_unit_of_work: int = 10_000


_infrastructure: KernelInfrastructure | None = None


def configure(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    event_bus: EventBus,
    publisher: Publisher | None = None,
    task_queue: TaskQueue | None = None,
    max_event_chain_depth: int = 10,
    max_events_per_unit_of_work: int = 10_000,
) -> None:
    """Install the process-wide infrastructure.

    The two limits bound one unit of work: generations of nested event dispatch (the
    command's own events are the first) and the total number of dispatched events.
    """
    global _infrastructure
    _require_positive_int("max_event_chain_depth", max_event_chain_depth)
    _require_positive_int("max_events_per_unit_of_work", max_events_per_unit_of_work)
    _infrastructure = KernelInfrastructure(
        session_factory=session_factory,
        event_bus=event_bus,
        publisher=publisher,
        task_queue=task_queue,
        max_event_chain_depth=max_event_chain_depth,
        max_events_per_unit_of_work=max_events_per_unit_of_work,
    )


def _require_positive_int(name: str, value: int) -> None:
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value!r}")


def infrastructure() -> KernelInfrastructure:
    if _infrastructure is None:
        raise NotConfiguredError("fast_ddd_adapter.configure() was not called at startup")
    return _infrastructure


def task_queue() -> TaskQueue:
    queue = infrastructure().task_queue
    if queue is None:
        raise NotConfiguredError("no task queue configured; pass one to configure()")
    return queue


def create_engine(
    dsn: str,
    *,
    application_name: str,
    lock_timeout_ms: int = 5_000,
    statement_timeout_ms: int = 30_000,
    idle_in_transaction_session_timeout_ms: int = 60_000,
    pool_size: int = 5,
    max_overflow: int = 10,
) -> AsyncEngine:
    server_settings = {
        "application_name": application_name,
        "lock_timeout": str(lock_timeout_ms),
        "statement_timeout": str(statement_timeout_ms),
        "idle_in_transaction_session_timeout": str(idle_in_transaction_session_timeout_ms),
    }
    engine = create_async_engine(
        dsn,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        connect_args={"server_settings": server_settings},
    )
    instrument_engine(engine, pool_name=application_name, max_connections=pool_size + max_overflow)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@contextmanager
def system_context(reason: str) -> Generator[None]:
    """Exempt the current unit of work from tenant filtering; every use is logged."""
    logger.warning("tenant filtering disabled: %s", reason)
    with tenant_exemption():
        yield
