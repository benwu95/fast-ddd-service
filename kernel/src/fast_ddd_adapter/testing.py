from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fast_ddd.context import User, unit_of_work_context
from fast_ddd_adapter.session import SessionProvider, session_provider_scope


@dataclass(slots=True)
class StatementCounter:
    statements: list[str] = field(default_factory=list[str])

    @property
    def count(self) -> int:
        return len(self.statements)


@contextmanager
def count_statements(engine: AsyncEngine) -> Generator[StatementCounter]:
    """Count SQL statements sent to the database (one per round trip)."""
    counter = StatementCounter()

    def before_cursor_execute(*args: Any) -> None:
        counter.statements.append(str(args[2]))

    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", before_cursor_execute)


@contextmanager
def unit_of_work_scope(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    organization_id: UUID | None,
    trace_id: str | None = None,
) -> Generator[SessionProvider]:
    """Set up the same per-unit-of-work context the HTTP middleware and MQ wrapper create."""
    provider = SessionProvider(session_factory)
    with (
        unit_of_work_context(user=user, organization_id=organization_id, trace_id=trace_id),
        session_provider_scope(provider),
    ):
        yield provider
