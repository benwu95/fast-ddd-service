from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from typing import cast

from fast_ddd.context import event_scope
from fast_ddd.events import DomainEvent

type EventHandler[E: DomainEvent] = Callable[[E], Awaitable[None]]


class EventBus:
    """In-process dispatcher; handlers are registered explicitly at wiring time."""

    def __init__(self) -> None:
        self._handlers: defaultdict[type[DomainEvent], list[EventHandler[DomainEvent]]] = (
            defaultdict(list)
        )

    def subscribe[E: DomainEvent](self, event_type: type[E], handler: EventHandler[E]) -> None:
        self._handlers[event_type].append(cast(EventHandler[DomainEvent], handler))

    def handlers_for(self, event: DomainEvent) -> list[EventHandler[DomainEvent]]:
        return list(self._handlers.get(type(event), ()))

    async def dispatch(self, events: Iterable[DomainEvent]) -> None:
        for event in events:
            for handler in self.handlers_for(event):
                with event_scope(event_id=event.event_id, organization_id=event.organization_id):
                    await handler(event)
