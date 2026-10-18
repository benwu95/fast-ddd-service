from dataclasses import dataclass, field
from typing import ClassVar
from uuid import UUID, uuid4

import pendulum

from fast_ddd.context import User, current_parent_event_id, current_trace_id


def _now() -> pendulum.DateTime:
    return pendulum.now("UTC")


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base for domain events.

    Source-aggregate fields are filled by ``AggregateRoot.add_event``; tracing fields are
    taken from ``fast_ddd.context`` when the event is created.
    """

    VERSION: ClassVar[int] = 1

    doer: User
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: pendulum.DateTime = field(default_factory=_now)
    trace_id: str | None = field(default_factory=current_trace_id)
    parent_event_id: UUID | None = field(default_factory=current_parent_event_id)
    organization_id: UUID | None = None
    aggregate_type: str = ""
    aggregate_id: UUID | None = None

    @property
    def name(self) -> str:
        return type(self).__name__
