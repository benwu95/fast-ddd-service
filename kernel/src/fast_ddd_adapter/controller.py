import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.batch import BatchItem, BatchResult
from fast_ddd.errors import DomainError, LockConflict
from fast_ddd_adapter.db_errors import to_domain_error
from fast_ddd_adapter.infrastructure import infrastructure
from fast_ddd_adapter.session import SessionProvider, current_session_provider

logger = logging.getLogger(__name__)


class EventHandlerFailedError(RuntimeError):
    """A handler rejected an event; this is a failure of the system, not of the command."""


class TransientBatchFailureError(RuntimeError):
    """A non-HTTP batch had temporary failures; retry the whole unit of work."""


@dataclass(frozen=True, slots=True)
class UnexpectedFailure:
    error: BaseException


type ItemOutcome[A] = A | DomainError | UnexpectedFailure


@dataclass(slots=True)
class BatchOutcome[Id: UUID, A: AggregateRoot]:
    results: dict[Id, ItemOutcome[A]] = field(default_factory=dict[Id, "ItemOutcome[A]"])

    def has_transient_failure(self) -> bool:
        return any(isinstance(r, UnexpectedFailure | LockConflict) for r in self.results.values())


async def _run_command[T](provider: SessionProvider, operation: Callable[[], Awaitable[T]]) -> T:
    mark = provider.mark()
    try:
        result = await operation()
    except DBAPIError as error:
        domain_error = to_domain_error(error)
        if domain_error is None:
            raise
        raise domain_error from error
    events = provider.take_pending_events(mark)
    with provider.protect(provider.saved_since(mark)):
        try:
            await infrastructure().event_bus.dispatch(events)
        except DomainError as error:
            raise EventHandlerFailedError(str(error)) from error
    return result


async def execute[T](operation: Callable[[], Awaitable[T]]) -> T:
    """Run one command: own the transaction when outermost, else run inside a SAVEPOINT."""
    provider = current_session_provider()
    nested = provider.is_active
    async with provider:
        if not nested:
            return await _run_command(provider, operation)
        async with provider.savepoint():
            return await _run_command(provider, operation)


async def run_batch[Id: UUID, A: AggregateRoot, P](
    items: Sequence[BatchItem[Id, P]],
    *,
    batch: Callable[[Sequence[BatchItem[Id, P]]], Awaitable[BatchResult[Id, A]]],
    single: Callable[[BatchItem[Id, P]], Awaitable[A]],
    raise_on_transient: bool = False,
) -> BatchOutcome[Id, A]:
    """Whole batch first; on an unexpected failure, fall back to one unit of work per item.

    Lock conflicts in the whole-batch phase fail the whole request. Non-HTTP callers pass
    ``raise_on_transient`` so a temporary per-item failure retries the whole message.
    """
    try:
        result = await execute(lambda: batch(items))
    except LockConflict:
        raise
    except Exception:
        logger.warning("batch failed as a whole, falling back to one item at a time", exc_info=True)
        outcome = await _run_one_by_one(items, single)
    else:
        outcome = BatchOutcome[Id, A]()
        for item in items:
            succeeded = result.succeeded.get(item.id)
            outcome.results[item.id] = (
                succeeded if succeeded is not None else result.failed[item.id]
            )
    if raise_on_transient and outcome.has_transient_failure():
        raise TransientBatchFailureError(f"{len(items)} items, retry the unit of work")
    return outcome


async def _run_one_by_one[Id: UUID, A: AggregateRoot, P](
    items: Sequence[BatchItem[Id, P]], single: Callable[[BatchItem[Id, P]], Awaitable[A]]
) -> BatchOutcome[Id, A]:
    outcome = BatchOutcome[Id, A]()
    for item in items:
        try:
            outcome.results[item.id] = await execute(lambda item=item: single(item))
        except DomainError as error:
            outcome.results[item.id] = error
        except Exception as error:
            logger.exception("batch item %s failed unexpectedly", item.id)
            outcome.results[item.id] = UnexpectedFailure(error)
    return outcome
