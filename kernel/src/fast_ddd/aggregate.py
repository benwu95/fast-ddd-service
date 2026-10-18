import re
from collections.abc import Sequence
from dataclasses import replace
from typing import ClassVar
from uuid import UUID, uuid4

import pendulum

from fast_ddd.events import DomainEvent


def new_id() -> UUID:
    return uuid4()


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class AggregateRoot:
    """Base for aggregate roots.

    Holds only persistence-lifecycle fields; business state lives in subclasses.
    ``version == 0`` marks an aggregate that has never been saved.
    """

    bounded_context: ClassVar[str]

    def __init__(
        self,
        *,
        id: UUID,
        organization_id: UUID | None,
        version: int = 0,
        created_at: pendulum.DateTime | None = None,
        updated_at: pendulum.DateTime | None = None,
    ) -> None:
        now = pendulum.now("UTC")
        self.id = id
        self.organization_id = organization_id
        self.version = version
        self.created_at = created_at or now
        self.updated_at = updated_at or self.created_at
        self.is_delete = False
        self._domain_events: list[DomainEvent] = []

    @classmethod
    def aggregate_type(cls) -> str:
        return _snake(cls.__name__)

    @classmethod
    def error_namespace(cls) -> str:
        return f"{cls.bounded_context}.{cls.aggregate_type()}"

    @property
    def is_new(self) -> bool:
        return self.version == 0

    @property
    def domain_events(self) -> tuple[DomainEvent, ...]:
        return tuple(self._domain_events)

    def add_event(self, event: DomainEvent) -> None:
        self._domain_events.append(
            replace(
                event,
                organization_id=self.organization_id,
                aggregate_type=self.aggregate_type(),
                aggregate_id=self.id,
            )
        )

    def pull_events(self) -> list[DomainEvent]:
        events, self._domain_events = self._domain_events, []
        return events

    def restore_events(self, events: Sequence[DomainEvent]) -> None:
        self._domain_events[:0] = events

    def mark_deleted(self) -> None:
        self.is_delete = True
