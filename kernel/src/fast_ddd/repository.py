from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fast_ddd.aggregate import AggregateRoot


@dataclass(frozen=True, slots=True)
class SearchPage[A: AggregateRoot]:
    total: int
    items: list[A]


class Repository[Id: UUID, A: AggregateRoot](Protocol):
    async def load_many(self, ids: Sequence[Id], *, lock: bool) -> dict[Id, A]: ...

    async def save_many(self, aggregates: Sequence[A]) -> None: ...
