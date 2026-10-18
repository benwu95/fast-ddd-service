import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Hashable
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import pendulum
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.events import DomainEvent

logger = logging.getLogger(__name__)

type Hook = Callable[[], Awaitable[None]]


class SessionNotActiveError(RuntimeError):
    pass


class AlreadySavedInThisCommandError(RuntimeError):
    """An event handler tried to save an aggregate whose state is in the command's response."""


@dataclass(frozen=True, slots=True)
class Mark:
    after_commit: int
    saved: int
    pending_events: int


class SessionProvider:
    """Owns one transaction per unit of work.

    Only the outermost scope commits or rolls back. After-commit hooks, the record of saved
    aggregates and the pending-event list all follow SAVEPOINT rollbacks.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._depth = 0
        self._after_commit: list[Hook] = []
        self._on_rollback: list[Hook] = []
        self._saved: list[Hashable] = []
        self._persistence: list[
            tuple[AggregateRoot, int, pendulum.DateTime, list[DomainEvent]]
        ] = []
        self._pending_events: list[DomainEvent] = []
        self._protected: set[Hashable] = set()
        self._loaded: dict[Hashable, object] = {}

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise SessionNotActiveError("no active transaction; enter the SessionProvider first")
        return self._session

    @property
    def is_outermost(self) -> bool:
        return self._depth == 1

    @property
    def is_active(self) -> bool:
        return self._depth > 0

    async def __aenter__(self) -> Self:
        if self._depth == 0:
            self._session = self._session_factory()
        self._depth += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._depth -= 1
        if self._depth > 0:
            return
        session = self.session
        failure = exc
        try:
            if failure is None:
                try:
                    await session.commit()
                except BaseException as error:
                    failure = error
            if failure is not None:
                try:
                    await session.rollback()
                except BaseException:
                    logger.exception("transaction rollback failed")
                finally:
                    self._restore(Mark(0, 0, 0))
            kind = "after-commit" if failure is None else "on-rollback"
            hooks = list(self._after_commit if failure is None else self._on_rollback)
        finally:
            try:
                await session.close()
            except BaseException as error:
                if failure is None:
                    failure = error
                else:
                    logger.exception("transaction close failed")
            finally:
                self._reset()
        try:
            await self._run_hooks(hooks, kind)
        except BaseException:
            if failure is None:
                raise
            logger.exception("transaction hook interrupted")
        if failure is not None and failure is not exc:
            raise failure

    def mark(self) -> Mark:
        return Mark(len(self._after_commit), len(self._saved), len(self._pending_events))

    def _restore(self, mark: Mark) -> None:
        for aggregate, version, updated_at, events in reversed(self._persistence[mark.saved :]):
            aggregate.version = version
            aggregate.updated_at = updated_at
            aggregate.restore_events(events)
        del self._persistence[mark.saved :]
        del self._after_commit[mark.after_commit :]
        del self._saved[mark.saved :]
        del self._pending_events[mark.pending_events :]
        self._loaded.clear()

    @asynccontextmanager
    async def savepoint(self) -> AsyncGenerator[None]:
        mark = self.mark()
        try:
            async with self.session.begin_nested():
                yield
        except BaseException:
            self._restore(mark)
            raise

    def _require_active(self) -> None:
        if not self.is_active:
            raise SessionNotActiveError("no active transaction; enter the SessionProvider first")

    def after_commit(self, hook: Hook) -> None:
        self._require_active()
        self._after_commit.append(hook)

    def on_rollback(self, hook: Hook) -> None:
        self._require_active()
        self._on_rollback.append(hook)

    def keep_loaded(self, key: Hashable, model: object) -> None:
        # The session's identity map only holds weak references; without this the ORM rows
        # converted to domain objects are collected and later reloaded without load options.
        self._loaded[key] = model

    def loaded(self, key: Hashable) -> object | None:
        return self._loaded.get(key)

    def record_saved(self, aggregate: AggregateRoot) -> list[DomainEvent]:
        key = (type(aggregate), aggregate.id)
        if key in self._protected:
            raise AlreadySavedInThisCommandError(
                f"{key!r} was saved by the command itself; change it in the domain method instead"
            )
        events = aggregate.pull_events()
        self._persistence.append((aggregate, aggregate.version, aggregate.updated_at, events))
        self._saved.append(key)
        self._pending_events.extend(events)
        return events

    def saved_since(self, mark: Mark) -> list[Hashable]:
        return self._saved[mark.saved :]

    def take_pending_events(self, mark: Mark) -> list[DomainEvent]:
        events = self._pending_events[mark.pending_events :]
        del self._pending_events[mark.pending_events :]
        return events

    @contextmanager
    def protect(self, keys: list[Hashable]) -> Generator[None]:
        added = [key for key in keys if key not in self._protected]
        self._protected.update(added)
        try:
            yield
        finally:
            self._protected.difference_update(added)

    async def _run_hooks(self, hooks: list[Hook], kind: str) -> None:
        for hook in hooks:
            try:
                await hook()
            except Exception:
                logger.exception("%s hook failed", kind)

    def _reset(self) -> None:
        self._session = None
        self._after_commit.clear()
        self._on_rollback.clear()
        self._saved.clear()
        self._persistence.clear()
        self._pending_events.clear()
        self._protected.clear()
        self._loaded.clear()


_current: ContextVar[SessionProvider | None] = ContextVar("fast_ddd_session_provider", default=None)


def current_session_provider() -> SessionProvider:
    provider = _current.get()
    if provider is None:
        raise SessionNotActiveError("no SessionProvider in this context; run inside a unit of work")
    return provider


@contextmanager
def session_provider_scope(provider: SessionProvider) -> Generator[SessionProvider]:
    token = _current.set(provider)
    try:
        yield provider
    finally:
        _current.reset(token)
