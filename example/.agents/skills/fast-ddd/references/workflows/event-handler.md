# React to a domain event

## When to use

- A domain event of this service must trigger a side effect: publish an integration message to other services, enqueue a background task, or change a different aggregate through its controller.
- Prefer an event handler over calling one more use case from the controller when the reaction is a consequence of the event rather than part of the command; see "When to use an event handler instead of calling a use case" in `references/decisions.md`.
- Not for consuming messages from another service (use `references/workflows/mq-consumer.md`) and not for the task handler itself (use `references/workflows/background-task-and-cron.md`).

## Files to change

- `app/adapter/event_handler/<context>/<aggregate>_event_handler.py`: the handlers and a `register(bus: EventBus)` function.
- `app/adapter/event_handler/__init__.py` and `app/adapter/event_handler/<context>/__init__.py`: empty package markers; the template ships neither, so create both. `fast-ddd-check-packages` reports either one when it is missing, so `make check` fails until both exist.
- `app/wiring.py`: call `<aggregate>_event_handler.register(bus)` from `wire_events`. The template names the unused parameter `_bus`; rename it to `bus`, or ruff reports the undefined name.
- `app/adapter/controller/<context>/task_names.py`: task name constants, only when a handler enqueues a task.
- `tests/port/test_<aggregate>_api.py` or `tests/port/test_<aggregate>_tasks.py`: assertions for the published messages or enqueued tasks.

## Rules to load

- `references/rules/layering.md`
- `references/rules/time-and-serialization.md`
- `references/rules/testing.md`

## Reference code

- `references/example/app/adapter/event_handler/billing/invoice_event_handler.py`: publishes integration messages and enqueues a task from `InvoiceVoided`; shows `register(bus)`.
- `references/example/app/core/billing/domain/events.py`: the event dataclasses a handler subscribes to.
- `references/example/app/adapter/controller/billing/task_names.py`: task names shared by the event handler and the task port.
- `references/example/app/wiring.py`: `wire_events` calls each context's `register(bus)`.
- `references/example/tests/conftest.py`: the `infrastructure` fixture wires the real `EventBus` with a `RecordingPublisher` and `PgQueuerTaskQueue`.
- `references/example/tests/port/test_invoice_api.py`: asserts `infrastructure.publisher.event_names()` and the `pgqueuer` rows after HTTP commands.
- `references/example/tests/port/test_invoice_tasks.py`: `test_rolled_back_void_enqueues_nothing`.

## Steps

1. Put handlers in the adapter layer. Core never publishes, enqueues or knows about the bus; the controller (`execute` or `run_batch`) collects the events saved in the current scope and dispatches them after the use case returns.
2. Write each handler as `async def handler(event: <EventType>) -> None`. Read `organization_id`, `aggregate_id` and the event's own fields from the event; never reload the aggregate for them, and never take `organization_id` from the context.
3. To publish to other services, call `publish_after_commit(integration_message(event, exchange=EXCHANGE))` from `fast_ddd_adapter.messaging`. The message is registered as an after-commit hook on the current `SessionProvider`: it is sent only after the outermost transaction commits and is discarded on rollback or SAVEPOINT rollback. Never publish through the broker directly. The envelope is fixed (`eventId`, `eventName`, `eventVersion`, `organizationId`, `occurredAt`, camelCase `data`); routing key defaults to the event name.
4. To start background work, call `await task_queue().enqueue(<TASK_NAME>, {...camelCase JSON...}, organization_id=event.organization_id)`. The handler runs inside the command's transaction, so the job row commits or rolls back with the business data. Define the task itself with `references/workflows/background-task-and-cron.md`.
5. To change another aggregate, call a controller method, never a use case or repository directly; the controller nests the call in a SAVEPOINT and dispatches the events it produces. Do not save an aggregate the triggering command itself saved: the kernel raises `AlreadySavedInThisCommandError`. Put that logic in the domain method instead.
6. Handlers of `*Deleted` events may use only the event's data; the aggregate no longer exists.
7. If the fan-out would lock many rows (for example every invoice of a customer), enqueue one task per chunk instead of doing the work in the handler; follow `references/workflows/batch-operation.md` step 5.
8. Register every handler in `register(bus)` with `bus.subscribe(<EventType>, handler)`, and call `register` from `wire_events` in `app/wiring.py`.
9. A handler that raises fails the command it runs in; a `DomainError` from a handler becomes `EventHandlerFailedError`, never the error's own status. Under `execute`, HTTP returns 500 `server.internal_error`, and an MQ message or a task is retried, then dead-lettered or held as failed. Under `run_batch`, the batch falls back to one item at a time and only the item whose handler failed fails: HTTP reports it as 500 in the 207 body, and non-HTTP callers pass `raise_on_transient=True` so the whole message or job is retried. The exception is an event chain that grows past `max_event_chain_depth` generations (default 10, the command's own events being the first) or `max_events_per_unit_of_work` events (default 10,000) in one unit of work: the kernel raises `EventChainLimitExceededError`. In the whole-batch phase `run_batch` re-raises it instead of falling back, so the whole request returns 500 and the whole message or job is retried; in the item-by-item fallback it fails only its item (500 in the 207) when the batch is its own unit of work, and is re-raised when the batch runs inside a message, task or handler so that unit of work rolls back. Both limits are `configure(...)` arguments in `app/bootstrap.py`; raise them only for a deliberate long chain. Do not catch errors to hide them.
10. Run `make check` from the service root.

## Required tests

- The command that emits the event results in the expected integration messages, asserted with `infrastructure.publisher.event_names()`, as in `references/example/tests/port/test_invoice_api.py`.
- The command enqueues the expected job, asserted on the `pgqueuer` table, as in the same test.
- A rolled-back transaction enqueues nothing, as in `test_rolled_back_void_enqueues_nothing` in `references/example/tests/port/test_invoice_tasks.py`; when the handler publishes, also assert that `infrastructure.publisher.messages` stays empty.
- When the handler changes another aggregate, a test that the target aggregate changed and that its own events were dispatched.
