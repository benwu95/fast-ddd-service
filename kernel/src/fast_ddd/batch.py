from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.errors import AggregateNotFound, DomainError, VersionMismatch
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
