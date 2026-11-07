from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.context import event_scope
from fast_ddd.errors import AggregateNotFound, DomainError, VersionMismatch
from fast_ddd.events import DomainEvent
from fast_ddd.repository import Repository


@dataclass(frozen=True, slots=True)
class BatchItem[Id: UUID, P]:
    id: Id
    payload: P
    expected_version: int | None = None


@dataclass(slots=True)
class BatchResult[Id: UUID, A: AggregateRoot]:
    succeeded: dict[Id, A] = field(default_factory=dict[Id, A])
    failed: dict[Id, DomainError] = field(default_factory=dict[Id, DomainError])


def check_version(aggregate: AggregateRoot, expected_version: int | None) -> None:
    if expected_version is not None and aggregate.version != expected_version:
        raise VersionMismatch(expected_version=expected_version, actual_version=aggregate.version)


async def apply_batch[Id: UUID, A: AggregateRoot, P](
    repository: Repository[Id, A],
    aggregate_type: type[A],
    items: Sequence[BatchItem[Id, P]],
    apply: Callable[[A, P], None],
) -> BatchResult[Id, A]:
    """Load with locks, apply the domain method per aggregate, save the successes once."""
    result = BatchResult[Id, A]()
    loaded = await repository.load_many([item.id for item in items], lock=True)
    for item in items:
        aggregate = loaded.get(item.id)
        if aggregate is None:
            result.failed[item.id] = AggregateNotFound(
                namespace=aggregate_type.error_namespace(),
                aggregate_type=aggregate_type.aggregate_type(),
                aggregate_id=item.id,
            )
            continue
        try:
            check_version(aggregate, item.expected_version)
            apply(aggregate, item.payload)
        except DomainError as error:
            result.failed[item.id] = error
            continue
        result.succeeded[item.id] = aggregate
    await repository.save_many(list(result.succeeded.values()))
    return result


async def apply_event_batch[Id: UUID, A: AggregateRoot, E: DomainEvent](
    repository: Repository[Id, A],
    aggregate_type: type[A],
    events: Sequence[E],
    target: Callable[[E], Id],
    apply: Callable[[A, E], None],
) -> list[A]:
    """Apply each event to its target, loading and saving every target once; all or nothing.

    Each application runs in its event's scope, so new events point to their own source.
    """
    if not events:
        return []
    ids = list(dict.fromkeys(target(event) for event in events))
    loaded = await repository.load_many(ids, lock=True)
    for aggregate_id in ids:
        if aggregate_id not in loaded:
            raise AggregateNotFound(
                namespace=aggregate_type.error_namespace(),
                aggregate_type=aggregate_type.aggregate_type(),
                aggregate_id=aggregate_id,
            )
    for event in events:
        with event_scope(event_id=event.event_id, organization_id=event.organization_id):
            apply(loaded[target(event)], event)
    aggregates = [loaded[aggregate_id] for aggregate_id in ids]
    await repository.save_many(aggregates)
    return aggregates


async def create_batch[Id: UUID, A: AggregateRoot, P](
    repository: Repository[Id, A],
    items: Sequence[BatchItem[Id, P]],
    create: Callable[[Id, P], A],
) -> BatchResult[Id, A]:
    result = BatchResult[Id, A]()
    for item in items:
        try:
            result.succeeded[item.id] = create(item.id, item.payload)
        except DomainError as error:
            result.failed[item.id] = error
    await repository.save_many(list(result.succeeded.values()))
    return result
