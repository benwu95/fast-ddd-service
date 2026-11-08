# Recipe: operation history

Placeholders as in `references/workflows/aggregate.md`. Add this only when the user asks to show who changed a resource and when.

## When to use

- A UI shows the change log of one aggregate: who did what, and when. Operation history is a domain feature, not part of the kernel (design §7.5).
- Default: read it from `domain_event`, which already stores one row per event with the doer, the time and the event body, indexed by `(organization_id, aggregate_type, aggregate_id)`. It needs no new writes and no migration.
- A separate history table, one row per entry, only when the log must outlive or differ from the events: queried across aggregates (for example every change by one user), filtered on its own indexed columns, or kept when `domain_event` is cleaned up.
- Never store the history as a JSONB array on the aggregate row: every update rewrites the growing array, and an archive snapshot would copy it (see `references/recipes/archive-snapshot.md`).
- When the UI must show old and new values, put the changed fields into the domain event the method already raises (for example `<Aggregate>Updated` carrying the changed fields); the event is the record, and both forms read it.

## Files to change

From `domain_event` (default):

- `app/adapter/repository/<context>/<aggregate>_repository.py`: `history(<aggregate>_id, *, offset, limit)`.
- `app/adapter/controller/<context>/<aggregate>_commands.py`: `<Aggregate>HistoryEntry` and `<Aggregate>HistoryPage`.
- `app/adapter/controller/<context>/<aggregate>_controller.py`: `history` through `execute`.
- `app/port/restful/<context>/<aggregate>_schemas.py`: `<Aggregate>HistoryQuery`, `<Aggregate>HistoryEntryResponse`.
- `app/port/restful/<context>/<aggregate>_router.py`: `GET /<aggregates>/{<aggregate>_id:uuid}/history`.
- `tests/adapter/test_<aggregate>_repository.py`, `tests/port/test_<aggregate>_api.py`.

Separate table, in addition: `app/adapter/repository/<context>/<aggregate>_history_model.py` (registered in `app/adapter/repository/models.py`), an adapter event handler that writes it (`references/workflows/event-handler.md`), a migration, and the table in the truncate list of the `session_factory` fixture in `tests/conftest.py`.

## Rules to load

- `references/rules/security.md`: tenant filtering on custom queries, 404 for another organization, bounded `limit` and `offset`.
- `references/rules/api.md`: sub-resource route, `PageResponse`, naming.
- `references/rules/time-and-serialization.md`: `occurredAt` in RFC 3339 UTC; `domain_event.body` is snake_case and must be mapped to camelCase fields.
- `references/rules/layering.md`: the query lives in the repository, the mapping in the port.

## Reference code

- `references/example/app/adapter/repository/billing/invoice_repository.py`: custom queries with `*self.tenant_conditions()` (`active_ids_of_customer`).
- `references/example/app/core/billing/domain/events.py`: the events whose fields the history shows.
- `references/example/app/port/restful/billing/invoice_schemas.py`: `InvoiceListQuery` bounds for `offset` and `limit`, `from_domain()` mappings.
- `references/example/app/port/restful/billing/invoice_router.py`: `list_invoices` returns `PageResponse`.
- `references/example/app/adapter/event_handler/billing/invoice_event_handler.py`: an adapter handler and `register(bus)`, for the separate table.

## Steps

1. Repository: `async def history(self, <aggregate>_id: <Aggregate>Id, *, offset: int, limit: int) -> tuple[int, list[DomainEventModel]]`. First `await self.load(<aggregate>_id, lock=False)` so a missing or other-organization aggregate is 404, then select `DomainEventModel` (from `fast_ddd_adapter.orm`) where `organization_id == aggregate.organization_id`, `aggregate_type == <Aggregate>.aggregate_type()` and `aggregate_id == <aggregate>_id`, ordered by `occurred_at, event_id`, with a count query for `total`. The three equality conditions match the `ix_domain_event_aggregate` index. A deleted aggregate's history is out of scope: `load` already returns 404.
2. Controller: `history` wraps the repository call in `execute` and maps each row to a frozen dataclass `<Aggregate>HistoryEntry(event_name, version, occurred_at, doer: User, body: Mapping[str, Any])`, returned in `<Aggregate>HistoryPage(total, items)`; both live in `<aggregate>_commands.py`, because the port must not import from `app.adapter.repository` (the `port` contract) and should not see ORM rows.
3. Port: `<Aggregate>HistoryQuery(RequestModel)` with the list route's `offset` and `limit` bounds. `<Aggregate>HistoryEntryResponse` has `eventName`, `occurredAt`, `doer` (`id`, `name`) and a `changes` object built by a hand-written mapping per event name and version. Expose only fields the aggregate's response model also exposes; skip unknown event names instead of returning the raw `body`, and handle every `version` the mapping has seen, because event formats evolve (`DomainEvent.VERSION`).
4. Route: `GET /<aggregates>/{<aggregate>_id:uuid}/history` with `dependencies=[require("<aggregate>:read")]`, returning `PageResponse[<Aggregate>HistoryEntryResponse]`.
5. Separate table only: the model has `organization_id`, `aggregate_id`, `occurred_at`, `doer_id`, `action` and a bounded `changes` JSON, with an index that starts with `organization_id`. An adapter event handler subscribed to the aggregate's events adds one row per event to the current session (`current_session_provider().session` from `fast_ddd_adapter.session`), inside the command's transaction, taking `organization_id` from the event. Use `subscribe_batch` for it when batches are large (`references/recipes/batch-event-handler.md`). Add the table to the test truncate list.
6. Write the tests, then `make check`.

## Required tests

- Repository: entries come back in occurrence order with the doer and the body of each event; another organization's events for the same `aggregate_id` value are never returned; `limit` and `offset` page the result and `total` counts all entries.
- API: 200 with the mapped `changes` and camelCase fields; another organization's aggregate is 404; 403 without `<aggregate>:read`; `limit` over the bound is 422. Follow the BOLA and permission tests in `references/example/tests/port/test_invoice_api.py`.
- Separate table: a rolled-back command writes no history row; a batch writes one row per item.

## Pitfalls

- Never return `domain_event.body` as is: it is the internal snake_case record and may hold fields the API does not expose.
- Never read history from `system_context()`; it is per organization like every other read.
