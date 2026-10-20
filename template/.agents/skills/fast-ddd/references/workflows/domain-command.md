# Add a domain command

Placeholders as in `references/workflows/aggregate.md`, plus `<command>` (snake_case verb, for example `void` or `mark_paid`; use it as is in Python names and permissions, and in kebab-case in URL paths: `/mark-paid`, `/batch-mark-paid`) and `<Commanded>` (past-tense event suffix, for example `Voided`).

## When to use

- The user asks for a business operation on one existing aggregate that is more than editing fields: void, approve, cancel, close, assign. It has its own name, its own invariant and its own event.
- Any state transition. Never model a transition as a PATCH of a `status` field: that moves the domain rule to the client. See "Domain command or PATCH" in `references/decisions.md`.
- Not for plain field edits (the default `PATCH`) or for applying the command to many aggregates at once (add the single command here, then `references/workflows/batch-operation.md`).

## Files to change

- `app/core/<context>/domain/<aggregate>.py`: the `<command>` method; with the first transition also the `<Aggregate>Status(StrEnum)`, its fields and a guard such as `_ensure_active`.
- `app/core/<context>/domain/errors.py`: the `DomainError` the invariant raises.
- `app/core/<context>/domain/events.py`: `<Aggregate><Commanded>`.
- `app/core/<context>/use_case/<aggregate>_use_case.py`: a `<command>` method.
- `app/adapter/controller/<context>/<aggregate>_controller.py`: a `<command>` method through `execute`.
- `app/adapter/controller/<context>/<aggregate>_commands.py`: a `statuses` filter on the search query when a status is introduced.
- `app/adapter/repository/<context>/<aggregate>_model.py`, `app/adapter/repository/<context>/<aggregate>_repository.py`: new columns, mapping, status filter in `search_<aggregates>()`.
- `app/port/restful/<context>/<aggregate>_schemas.py`: `<Command><Aggregate>Request` when the command takes arguments, new response fields, `status` list filter.
- `app/port/restful/<context>/<aggregate>_router.py`: `POST /<aggregates>/{<aggregate>_id:uuid}/<command>`.
- `alembic/versions/`: `make migration name="add <aggregate> <command>"` when columns were added.
- `tests/core/test_<aggregate>.py`, `tests/adapter/test_<aggregate>_repository.py` (when columns were added), `tests/port/test_<aggregate>_api.py`, `tests/test_error_catalog.py`, and `tests/support.py` (`ALL_PERMISSIONS`).

## Rules to load

- `references/rules/layering.md`: the rule lives in the domain method; controller and router only translate.
- `references/rules/api.md`: `/action` routes, 200 + `ETag`, 409 versus 422, error code format, lowercase enum values.
- `references/rules/time-and-serialization.md`: timestamps such as `voided_at` from `pendulum.now("UTC")`, params formatting.
- `references/rules/security.md`: one permission per action, `<aggregate>:<command>`.
- `references/rules/testing.md`: transition tests.

## Reference code

- `references/example/app/core/billing/domain/invoice.py`: `InvoiceStatus` (`active`/`voided`), `void` (guard, change state, record `InvoiceVoided`), `_ensure_active` reused by `update` and `delete`.
- `references/example/app/core/billing/domain/errors.py`: `InvoiceAlreadyVoided`, `ErrorKind.CONFLICT` with `invoice_id`/`voided_at` params.
- `references/example/app/core/billing/domain/events.py`: `InvoiceVoided`.
- `references/example/app/core/billing/use_case/invoice_use_case.py`: `void` via `_load_checked` and `save`.
- `references/example/app/adapter/controller/billing/invoice_controller.py`: `InvoiceController.void`.
- `references/example/app/adapter/repository/billing/invoice_repository.py`: status/void columns in both mapping directions and the `statuses` filter.
- `references/example/app/port/restful/billing/invoice_schemas.py`: `VoidInvoiceRequest`, `status`/`voidReason`/`voidedAt` in `InvoiceResponse`, `status` in `InvoiceListQuery`.
- `references/example/app/port/restful/billing/invoice_router.py`: `void_invoice`.

## Steps

1. Name the command after the business act and agree on its invariant with the user: which states allow it, what it changes, what it takes as input.
2. First command that needs a state transition: add `<Aggregate>Status(StrEnum)` with lowercase values; the initial value describes the business state (the example uses `active`, not `created`). Add the status and any audit fields (for example `voided_at`, `void_reason`) to `__init__` with defaults, the ORM model, both mapping directions, the response model and a list filter. Existing commands that must not run in the new state call the same guard (`Invoice.update` and `Invoice.delete` call `_ensure_active`).
3. Error: a `DomainError` subclass named after the rejected rule (`<Aggregate>Already<Commanded>`), code `<context>.<aggregate>.<reason>`, `kind = ErrorKind.CONFLICT` (409) because the request could succeed in another state; `ErrorKind.INVALID` (422) only when the input can never succeed. Params are dataclass fields whose camelCase names match the `message` placeholders.
4. Domain method `<command>(self, <args>, doer: User) -> None`: check the invariant and raise first, then change state, then `self.add_event(<Aggregate><Commanded>(doer=doer, ...))`. Never mutate before the check; batch fallback relies on it.
5. Use case: `<command>(self, <aggregate>_id, <args>, expected_version: int | None, doer: User)` loads with `_load_checked`, calls the domain method, saves and returns the aggregate.
6. Controller: `<command>(...)` returns `await execute(lambda: self._use_case.<command>(..., expected_version, current_user()))`.
7. Router: `@router.post("/{<aggregate>_id:uuid}/<command>", dependencies=[require("<aggregate>:<command>")])`, function `<command>_<aggregate>`, `expected_version: ExpectedVersion`, a request body only when there are arguments, response 200 with the `ETag` header and the full resource. Add the permission to `ALL_PERMISSIONS` in `tests/support.py`.
8. Migration when columns were added: with `DATABASE_URL` pointing at a database migrated by `uv run --frozen fast-ddd-alembic upgrade heads`, run `make migration name="add <aggregate> <command>"`, review the revision, then `uv run --frozen fast-ddd-alembic upgrade heads` and `uv run --frozen fast-ddd-alembic check` (see step 8 of `references/workflows/aggregate.md`).
9. If other services must learn about the event, follow `references/workflows/event-handler.md`; do not publish from the command.
10. Write the tests, then `make check`.

## Required tests

- Domain (`tests/core/test_<aggregate>.py`): the allowed transition changes state and records exactly one event; repeating it or running it from a disallowed state raises the specific error with its params; other commands guarded by the new state are rejected. Follow `test_void_moves_active_to_voided_once` and `test_voided_invoices_are_frozen` in `references/example/tests/core/test_invoice.py`.
- API (`tests/port/test_<aggregate>_api.py`): 200 with the new `ETag` and state, 409 with the domain code and params on the second call, 412 stale `If-Match`, 428 missing, 404 for another organization, 403 without `<aggregate>:<command>`, 422 for invalid arguments, list filtering by the new status. Follow `test_delete_and_void` and `test_write_preconditions` in `references/example/tests/port/test_invoice_api.py` and the void cases in `references/example/tests/port/test_invoice_http_contract.py`.
- Repository: extend the mapping round-trip test with the new columns (`references/example/tests/adapter/test_invoice_repository.py`).
- Error catalog: add the new code with status and params to `tests/test_error_catalog.py` (`references/example/tests/test_error_catalog.py`).
