import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.batch import BatchItem, BatchResult
from fast_ddd.errors import DomainError, LockConflict
from fast_ddd.events import DomainEvent
from fast_ddd_adapter.db_errors import to_domain_error
from fast_ddd_adapter.infrastructure import infrastructure
from fast_ddd_adapter.session import SessionProvider, current_session_provider

logger = logging.getLogger(__name__)


class EventHandlerFailedError(RuntimeError):
    """A handler rejected an event; this is a failure of the system, not of the command."""


class TransientBatchFailureError(RuntimeError):
    """A non-HTTP batch had temporary failures; retry the whole unit of work."""


class EventChainLimitExceededError(RuntimeError):
    """Event dispatch went deeper or produced more events than configure() allows."""


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
    if not events:
        return result
    _check_event_chain(provider, events)
    with provider.protect(provider.saved_since(mark)), provider.dispatching(len(events)):
        try:
            await infrastructure().event_bus.dispatch(events)
        except DomainError as error:
            raise EventHandlerFailedError(str(error)) from error
    return result


def _check_event_chain(provider: SessionProvider, events: list[DomainEvent]) -> None:
    limits = infrastructure()
    generation = provider.dispatch_depth + 1
    if generation > limits.max_event_chain_depth:
        raise EventChainLimitExceededError(
            f"event generation {generation} exceeds max_event_chain_depth="
            f"{limits.max_event_chain_depth} (first event: {events[0].name})"
        )
    total = provider.dispatched_events + len(events)
    if total > limits.max_events_per_unit_of_work:
        raise EventChainLimitExceededError(
            f"{total} events exceed max_events_per_unit_of_work="
            f"{limits.max_events_per_unit_of_work} (first event: {events[0].name})"
        )


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

    Lock conflicts and an exceeded event chain limit in the whole-batch phase fail the whole
    request. In the fallback, an exceeded limit fails only its item when each item is its own
    unit of work; nested in another unit of work it is raised, since recording it as an item
    result would let the enclosing unit of work commit the runaway chain's caller. Non-HTTP
    callers pass ``raise_on_transient`` so a temporary per-item failure retries the whole message.
    """
    nested = current_session_provider().is_active
    try:
        result = await execute(lambda: batch(items))
    except (LockConflict, EventChainLimitExceededError):
        raise
    except Exception:
        logger.warning("batch failed as a whole, falling back to one item at a time", exc_info=True)
        outcome = await _run_one_by_one(items, single, nested=nested)
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
    items: Sequence[BatchItem[Id, P]],
    single: Callable[[BatchItem[Id, P]], Awaitable[A]],
    *,
    nested: bool,
) -> BatchOutcome[Id, A]:
    outcome = BatchOutcome[Id, A]()
    for item in items:
        try:
            outcome.results[item.id] = await execute(lambda item=item: single(item))
        except DomainError as error:
            outcome.results[item.id] = error
        except Exception as error:
            if nested and isinstance(error, EventChainLimitExceededError):
                raise
            logger.exception("batch item %s failed unexpectedly", item.id)
            outcome.results[item.id] = UnexpectedFailure(error)
    return outcome
