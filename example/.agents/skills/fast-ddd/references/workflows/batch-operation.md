# Add a batch operation

Placeholders as in `references/workflows/domain-command.md`. The example is batch-void: `POST /invoices/batch-void`.

## When to use

- The user asks to run an existing single-aggregate command on many aggregates in one request (batch-void), or to process many ids from a message as one task per chunk.
- The single command must exist first, with its domain method, use case method and controller method. If not, run `references/workflows/domain-command.md` first.
- The batch changes only I/O and orchestration: one locked load, one flush, partial success. The rules stay per aggregate in the domain method; the domain layer gets no batch concept.

## Files to change

- `app/core/<context>/use_case/<aggregate>_use_case.py`: `<command>_many`.
- `app/adapter/controller/<context>/<aggregate>_controller.py`: `<command>_many` through `run_batch`.
- `app/port/restful/<context>/<aggregate>_schemas.py`: `Batch<Command>Item` and `Batch<Command><Aggregates>Request`.
- `app/port/restful/<context>/<aggregate>_router.py`: `POST /<aggregates>/batch-<command>`.
- `tests/adapter/test_<aggregate>_controller.py`, `tests/port/test_<aggregate>_api.py`.
- No migration, wiring, model or permission change: the batch reuses the single command's permission.

## Rules to load

- `references/rules/layering.md`: core helper for steps 1 to 3, adapter runner for transactions and event dispatch.
- `references/rules/api.md`: `batch-` prefix, `{"items": [...]}` body, 207 per-item results, item limit.
- `references/rules/security.md`: tenant filtering turns other organizations' ids into 404 items; same permission as the single command.
- `references/rules/testing.md`: round-trip and 207 tests.

## Reference code

- `references/example/app/core/billing/use_case/invoice_use_case.py`: `void_many` with `apply_batch`, next to the single `void`.
- `references/example/app/adapter/controller/billing/invoice_controller.py`: `void_many` with `run_batch(batch=..., single=...)`; `void_invoices` runs one chunk in a task with `raise_on_transient=True`, and `enqueue_customer_invoice_voids` enqueues one task per chunk of a message's ids.
- `references/example/app/port/restful/billing/invoice_schemas.py`: `BatchVoidItem`, `BatchVoidInvoicesRequest` with `max_length=MAX_BATCH_ITEMS`.
- `references/example/app/port/restful/billing/invoice_router.py`: `batch_void_invoices` with `ensure_unique_ids`, `parse_etag` and `batch_response`.

## Steps

1. Use case: `async def <command>_many(self, items: Sequence[BatchItem[<Aggregate>Id, P]], doer: User) -> BatchResult[<Aggregate>Id, <Aggregate>]` returning `await apply_batch(self._repository, <Aggregate>, items, lambda aggregate, payload: aggregate.<command>(payload, doer))`. `P` is the per-item argument (a `str` reason in the example; use a frozen dataclass for several). For a command without arguments, use `P = None`, `BatchItem(<Aggregate>Id(item.id), None, expected_version=...)` and `lambda aggregate, _: aggregate.<command>(doer)` (an unused `payload` name fails ruff ARG005); the controller's `single` then calls `self._use_case.<command>(item.id, item.expected_version, doer)`. `apply_batch` does `load_many(lock=True)` in id order, records missing ids as `not_found` and stale versions as `concurrency.etag_mismatch`, collects each `DomainError` per item and calls `save_many` once.
2. Controller: read `doer = current_user()` once, then `return await run_batch(items, batch=lambda batch: self._use_case.<command>_many(batch, doer), single=lambda item: self._use_case.<command>(item.id, item.payload, item.expected_version, doer))`. `run_batch` owns the transaction or SAVEPOINT, dispatches events, falls back to one unit of work per item on an unexpected failure, and raises a lock conflict in the whole-batch phase as a request-level 409. An `EventChainLimitExceededError` is re-raised from the whole-batch phase; in the fallback it fails only its item when the batch is its own unit of work, and is re-raised when the batch is nested.
3. Schemas: `Batch<Command>Item(RequestModel)` with `id: UUID`, `etag: str` and the command's arguments; `Batch<Command><Aggregates>Request(RequestModel)` with `items: Annotated[list[Batch<Command>Item], Field(min_length=1, max_length=MAX_BATCH_ITEMS)]`.
4. Router: `@router.post("/batch-<command>", status_code=status.HTTP_207_MULTI_STATUS, dependencies=[require("<aggregate>:<command>")])`, function `batch_<command>_<aggregates>`. Call `ensure_unique_ids([item.id for item in body.items])` first (422 `validation.failed` with an `errors` entry `validation.duplicate_id` per repeated id), build `BatchItem(<Aggregate>Id(item.id), <payload>, expected_version=parse_etag(item.etag))` for every item before calling the controller (a malformed etag is 400, an empty one 428, before anything changes), and return `batch_response(items, outcome, <Aggregate>Response.from_domain)`. The `{<aggregate>_id:uuid}` convertor keeps `/batch-<command>` from matching the single-item route regardless of order.
5. Non-HTTP callers (MQ subscriber, task): pass `expected_version=None` and `raise_on_transient=True`, and log the `DomainError` items; a transient failure raises so the whole message or task is retried. Run at most one chunk of `BULK_CHUNK_SIZE` ids per unit of work (a module-level constant you define in the controller; the kernel does not provide it, and `references/example/app/adapter/controller/billing/invoice_controller.py` sets it to 100, the HTTP batch limit): every `run_batch` in one message or task shares its unit of work, so their events count toward one `max_events_per_unit_of_work` (default 10,000) and their rows stay locked until it commits. When the number of ids has no upper bound, split them with `itertools.batched(ids, BULK_CHUNK_SIZE, strict=False)` (ruff B911 requires the explicit `strict`) and enqueue one task per chunk that calls `run_batch` once, as `enqueue_customer_invoice_voids` and `void_invoices` do (see `references/workflows/background-task-and-cron.md`). The ids were listed when the task was enqueued, so the task first reads again which of them still match the selection and locks them, inside its own unit of work (`active_ids_of_customer(customer_id, among=invoice_ids, lock=True)`: `SELECT ... FOR UPDATE` in id order, the order `load_many` locks in), and skips the rest with a warning. Without the re-read an aggregate changed since the enqueue, such as an invoice moved to another customer, is processed anyway; without the lock a change committed between the re-read and the batch's locked load still slips through. Bound every payload field at the task's boundary as the HTTP schema does, so a bad job is rejected once instead of retried: `VoidInvoicesData` bounds the id list with `Field(min_length=1, max_length=BULK_CHUNK_SIZE)` and takes `reason` as the `Reason` type of `references/example/app/port/billing/fields.py`, which the HTTP schema shares, never as a type imported from another transport's module; the shared type lives in a port capability subpackage (`references/rules/layering.md`, Shared code). Keep `BULK_CHUNK_SIZE` times the events one item dispatches (its own events plus the events its handlers chain) at or below `max_events_per_unit_of_work`; otherwise the whole-batch phase of every chunk raises `EventChainLimitExceededError`, and the task is retried until it is held as failed.
6. Write the tests, then `make check`.

## Required tests

- Round trips (`tests/adapter/test_<aggregate>_controller.py`): with an `EventBus()` that has no handlers, the statement count from `count_statements(engine)` is equal for N=1 and N=50. Follow `test_batch_void_round_trips_do_not_grow_with_the_batch` in `references/example/tests/adapter/test_invoice_controller.py`.
- 207 results (`tests/port/test_<aggregate>_api.py`): one request mixing success (200 with `data` and the new `etag`), stale etag (412 `concurrency.etag_mismatch`), a domain rejection (409 with the domain code) and an unknown or other-organization id (404), in request order with `index`. Follow `test_batch_void_reports_each_item` in `references/example/tests/port/test_invoice_api.py`.
- Request-level errors: duplicate ids 422 `validation.failed` whose `errors` hold `validation.duplicate_id` with pointer `#/items/<n>/id` for each repeated occurrence; more than `MAX_BATCH_ITEMS` items 422 `validation.failed` with `errors[0].code` `validation.too_long`; missing item `etag` 422; 403 without the permission. Follow `test_batch_void_rejects_duplicates_and_oversized_batches` in `references/example/tests/port/test_invoice_api.py`.
- An item etag that is not a single strong ETag (`*`, weak, oversized) is 400 `concurrency.invalid_if_match`, an empty one is 428 `concurrency.precondition_required`; in both cases no item changes. Follow `references/example/tests/port/test_invoice_etag_limits.py`.
- Chunked non-HTTP use, when added: follow `test_void_invoices_skips_voided_and_missing_ones` and `test_customer_invoices_are_enqueued_in_chunks` in `references/example/tests/adapter/test_invoice_controller.py`, `test_invoices_past_the_event_limit_are_voided_one_chunk_per_unit_of_work` in `references/example/tests/port/test_customer_subscriber.py`, and `test_transient_failure_retries_the_whole_void_chunk`, `test_invoice_moved_to_another_customer_after_enqueue_is_not_voided`, `test_invoice_cannot_move_to_another_customer_while_its_chunk_is_voided`, `test_invoice_locked_by_another_transaction_is_voided_once_released`, `test_void_invoices_payload_holds_one_chunk` and `test_void_invoices_payload_reason_fits_the_column` in `references/example/tests/port/test_invoice_tasks.py`, and `test_locked_customer_reread_uses_a_fixed_order` in `references/example/tests/adapter/test_invoice_repository.py`.

## Pitfalls

- Never replace the batch with a bulk SQL `UPDATE`; it skips domain rules, events and archive.
- Do not loop over the single controller method instead of `run_batch`; that is one unit of work per item and the round trips grow with N.
- Other batch forms are recipes, used only on request: batch-create uses `create_batch` from `fast_ddd.batch` and `batch_response(..., success_status=201)`; batch-delete passes `success_status=204`.
