from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from typing import cast
from uuid import UUID

from fast_ddd.context import event_scope
from fast_ddd.events import DomainEvent

type EventHandler[E: DomainEvent] = Callable[[E], Awaitable[None]]
type BatchEventHandler[E: DomainEvent] = Callable[[list[E]], Awaitable[None]]


class EventBus:
    """In-process dispatcher; handlers are registered explicitly at wiring time."""

    def __init__(self) -> None:
        self._handlers: defaultdict[type[DomainEvent], list[EventHandler[DomainEvent]]] = (
            defaultdict(list)
        )
        self._batch_handlers: defaultdict[
            type[DomainEvent], list[BatchEventHandler[DomainEvent]]
        ] = defaultdict(list)

    def subscribe[E: DomainEvent](self, event_type: type[E], handler: EventHandler[E]) -> None:
        self._handlers[event_type].append(cast(EventHandler[DomainEvent], handler))

    def subscribe_batch[E: DomainEvent](
        self, event_type: type[E], handler: BatchEventHandler[E]
    ) -> None:
        """Receive one list per event type and organization of each dispatch."""
        self._batch_handlers[event_type].append(cast(BatchEventHandler[DomainEvent], handler))

    def handlers_for(self, event: DomainEvent) -> list[EventHandler[DomainEvent]]:
        return list(self._handlers.get(type(event), ()))

    async def dispatch(self, events: Iterable[DomainEvent]) -> None:
        """Run single handlers in event order, then each batch group in first-seen order."""
        events = list(events)
        for event in events:
            for handler in self.handlers_for(event):
                with event_scope(event_id=event.event_id, organization_id=event.organization_id):
                    await handler(event)
        groups: dict[tuple[type[DomainEvent], UUID | None], list[DomainEvent]] = {}
        for event in events:
            if type(event) in self._batch_handlers:
                groups.setdefault((type(event), event.organization_id), []).append(event)
        for (event_type, organization_id), group in groups.items():
            # A group of several events has no single source; only apply_event_batch
            # attributes each new event to its own source.
            source = group[0].event_id if len(group) == 1 else None
            for handler in list(self._batch_handlers[event_type]):
                with event_scope(event_id=source, organization_id=organization_id):
                    await handler(list(group))
