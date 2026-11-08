# Recipe: batch event handler

Placeholders as in `references/workflows/event-handler.md`, plus `<Target>` (the aggregate the handler changes) and `<react>` (the target's domain method). A single-event handler (`bus.subscribe`) stays the default; switch to a batch handler only when the user asks for it or a measured round-trip problem requires it.

## When to use

- The handler does database I/O, for example changes another aggregate through its controller, and the triggering commands run in large batches (batch routes, chunked tasks). A single-event handler costs about five round trips per event (SAVEPOINT, load, flush, `domain_event` insert, release), so the total grows with the batch size; a batch handler loads and saves all targets once per dispatch, and its round trips depend only on the chain depth and the number of groups (design §8.2).
- Not when the handler only publishes integration messages or enqueues one task per event: those add no round trips beyond the command's own flush.
- Not when the fan-out would lock many rows (for example each event touching every invoice of a customer): enqueue one task per chunk instead, as `references/workflows/batch-operation.md` step 5 describes.

## Files to change

- `app/adapter/event_handler/<context>/<aggregate>_event_handler.py`: the batch handler and its `bus.subscribe_batch` line in `register(bus)`.
- `app/core/<target_context>/use_case/<target>_use_case.py`: `<react>_many`.
- `app/adapter/controller/<target_context>/<target>_controller.py`: `<react>_many` through `execute`.
- `tests/adapter/test_<target>_controller.py` or `tests/port/test_<aggregate>_api.py`: the tests below.

## Rules to load

- `references/rules/layering.md`: handlers in adapter, use cases only through a controller, independent bounded contexts.
- `references/rules/testing.md`: the round-trip test.

## Reference code

- `references/example/app/adapter/event_handler/billing/invoice_event_handler.py`: handler module layout and `register(bus)`.
- `references/example/app/core/billing/use_case/invoice_use_case.py`: `void_many` passes the repository, the aggregate type and a lambda that calls the domain method, the same shape `apply_event_batch` takes.
- `references/example/app/adapter/controller/billing/invoice_controller.py`: controller methods wrapping a use case call in `execute`.
- `references/example/tests/adapter/test_invoice_controller.py`: `test_batch_void_round_trips_do_not_grow_with_the_batch` measures statements with `count_statements`.

## Steps

1. Use case: `<react>_many` returns `await apply_event_batch(self._repository, <Target>, events, target, apply)` from `fast_ddd.batch`. `target(event)` returns the `<Target>Id`; `apply(target, event)` calls the domain method, for example `lambda target, event: target.<react>(event.<field>, doer)`. When the event belongs to the same bounded context, type the method with that event. When it comes from another context, the core may not import it (the `bounded-contexts` contract): make the method generic, `async def <react>_many[E: DomainEvent](self, events: Sequence[E], target: Callable[[E], <Target>Id], apply: Callable[[<Target>, E], None]) -> list[<Target>]`, and let the adapter pass the two callables.
2. `apply_event_batch` removes duplicate targets, loads them once with `load_many(lock=True)`, applies the events in order, each inside its own event's scope so the new events point to their own source, and saves once with `save_many`. Two events for the same target change it once in the same flush, so its `version` grows by one. A missing target raises `AggregateNotFound` before anything is applied; a `DomainError` from the domain method propagates. It does not compare versions.
3. Controller: `async def <react>_many(self, events, ...) -> list[<Target>]` returns `await execute(lambda: self._use_case.<react>_many(...))`. `execute` nests the work in a SAVEPOINT of the command's transaction and dispatches the events it produces as the next generation, again as one batch.
4. Handler: `async def handler(events: list[<EventType>]) -> None` calls the controller once with the whole list. Register it with `bus.subscribe_batch(<EventType>, handler)` (`EventBus` from `fast_ddd.event_bus`) in `register(bus)`; it receives one list per event type and organization of each dispatch, in event order, after the single-event handlers of that dispatch have run. The exact event type is matched; subclasses are not included. Events without an organization form their own group.
5. Each call runs in that group's organization context, with any `system_context()` exemption turned off. With a single event in the group its `event_id` is the parent of new events; with several events there is no single parent, and only `apply_event_batch` links each new event to its own source.
6. All or nothing: any failure raises and fails the whole call. The nearest batch runner in its whole-batch phase (`run_batch`, also when nested) then falls back to one unit of work per item, where the handler receives one event per command and the result matches a single-event handler; the worst case costs the whole-batch attempt plus the item-by-item pass. Without a batch runner (`execute` of a single command) the command fails: 500 over HTTP, a retry over MQ and in tasks.
7. Order: dispatch becomes breadth-first (A1, A2, then B1, B2) instead of depth-first (A1, B1, A2, B2). Events of one aggregate keep their order; never depend on the order between different aggregates.
8. The chain limits still apply (`max_event_chain_depth`, default 10 generations; `max_events_per_unit_of_work`, default 10,000 events, both `configure(...)` arguments in `app/bootstrap.py`). An `EventChainLimitExceededError` is not caught by the handler; never wrap the controller call in `except Exception`.
9. The handler must not save an aggregate the triggering command itself saved (`AlreadySavedInThisCommandError`); handlers of `*Deleted` events use only the event's data.
10. Write the tests, then `make check`.

## Required tests

- Round trips: the triggering batch with the batch handler subscribed sends the same number of statements for N=1 and N=50, measured with `count_statements(engine)` from `fast_ddd_adapter.testing`, as in `test_batch_void_round_trips_do_not_grow_with_the_batch` in `references/example/tests/adapter/test_invoice_controller.py`, now with the real `wire_events` handlers.
- Shared target, when several events can reach one target: two events for the same target load it with one `FOR UPDATE` (`counter.statements`), increase its `version` by one, and each new `domain_event` row has the `parent_event_id` of its own source event.
- The grouping by organization and the chain limits are kernel behavior with kernel tests; do not repeat them.
- Failure: when the handler fails for one item of a batch route, the 207 reports that item as 500 and the other items succeed, as with a single-event handler; the same failure under a single command returns 500 and changes nothing.

## Pitfalls

- Do not keep both `subscribe` and `subscribe_batch` for the same reaction; the handler would run twice.
- Do not loop over the events calling the single controller method; that brings back one SAVEPOINT per event.
