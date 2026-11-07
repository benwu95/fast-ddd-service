# API rules

Source: design §9.2–9.10. Reference: `references/example/app/port/restful/billing/invoice_router.py` and `references/example/app/port/restful/billing/invoice_schemas.py`.

## Routing

One router per aggregate, `APIRouter(prefix="/<aggregates>")`, registered in `wire_http(app)`.

| Operation | Route | Success |
|---|---|---|
| list | `GET /<aggregates>` | 200, `PageResponse` (`total`, `items`); every item has `etag` |
| get | `GET /<aggregates>/{<aggregate>_id:uuid}` | 200 + `ETag` |
| create | `POST /<aggregates>` | 201 + `Location` + `ETag` + full resource |
| update | `PATCH /<aggregates>/{<aggregate>_id:uuid}` | 200 + `ETag` + full resource |
| delete | `DELETE /<aggregates>/{<aggregate>_id:uuid}` | 204 |
| domain command | `POST /<aggregates>/{<aggregate>_id:uuid}/<verb>` | 200 + `ETag` + full resource |
| batch | `POST /<aggregates>/batch-<verb>` | 207 + `BatchResponse` |

- Write every id path parameter with the Starlette convertor `{xxx_id:uuid}`. Without it, a plain `{xxx_id}` route declared earlier captures same-method requests to sibling paths: `GET /<aggregates>/export` returns 422 `uuid_parsing`, and a wrong-method request to `/batch-void` returns 422 instead of 405. With it, a malformed id matches no route and returns 404.
- Never add PUT. PATCH is the only update.
- Actions are verbs, POST only, kebab-case, written as `/<verb>` (never `:<verb>`); sub-resources are nouns. Collection-level batch operations use the `batch-` prefix.
- Every route declares `dependencies=[require("<aggregate>:<action>")]` (see `references/rules/security.md`).
- PATCH, DELETE and domain commands take the `ExpectedVersion` dependency from `fast_ddd_port.preconditions` (`If-Match`).
- Batch bodies are `{"items": [...]}` with `Field(min_length=1, max_length=MAX_BATCH_ITEMS)` (100). Each item carries `id` and `etag` (batch-create excepted) plus the command's arguments. The route calls `ensure_unique_ids()`, converts each `etag` with `parse_etag()`, and builds the response with `batch_response()`.
- Success responses have no envelope. Write responses return the full resource and the new `ETag`.
- List query models inherit `RequestModel`; `limit` uses `le=MAX_BATCH_ITEMS`, `offset` has an upper bound, and search and sort fields are whitelisted with `Field(pattern=...)`.
- Declare a response model for every route; the kernel declares the shared problem+json schema.

## Status codes

| Status | When | Error code |
|---|---|---|
| 200 / 201 / 204 | read, update or command / create / delete succeeded | — |
| 207 | any batch that reaches its results, whatever the item outcomes | per item in `results` |
| 400 | malformed JSON; `If-Match` or a batch item `etag` is `*`, several values or a weak ETag | `request.malformed_json`, `concurrency.invalid_if_match` |
| 401 | missing, invalid or expired token | `auth.unauthenticated`, `auth.token_invalid`, `auth.token_expired` |
| 403 | authenticated without the permission | `auth.permission_denied` |
| 404 | resource missing or owned by another organization; unknown route or malformed id | `<context>.<aggregate>.not_found`, `request.route_not_found` |
| 405 | method not supported | `request.method_not_allowed` |
| 409 | conflicts with the resource's current state; client id already exists; lock timeout or deadlock | `<context>.<aggregate>.<reason>`, `<context>.<aggregate>.already_exists`, `concurrency.lock_conflict` |
| 412 | `If-Match` or item `etag` differs from the current version | `concurrency.etag_mismatch` |
| 415 | a POST, PUT or PATCH request with a body whose Content-Type is not `application/json`, checked before authentication and on public paths too | `request.unsupported_media_type` |
| 422 | schema validation, batch over the limit, duplicate ids, missing item `etag`; a business rule that fails in any state | `validation.failed`, `<context>.<aggregate>.<reason>` |
| 428 | `If-Match` missing or empty, or a batch item `etag` is empty | `concurrency.precondition_required` |
| 500 | unexpected error; no exception content in the body | `server.internal_error` |

- 409 or 422: if the same request could succeed when the resource is in another state, use 409 (`ErrorKind.CONFLICT`); if it can never succeed, use 422 (`ErrorKind.INVALID`).
- The domain knows no HTTP. `fast_ddd_port` maps `ErrorKind` to status: `INVALID` 422, `CONFLICT` 409, `NOT_FOUND` 404, `ALREADY_EXISTS` 409, `PRECONDITION_FAILED` 412.
- Checks run in this order: 415 (middleware, before authentication), 401 (middleware), 404 or 405 (routing), 400 (malformed JSON), 403 (`require()`), 428 or 400 (`If-Match`), 422 (schema), 404 (load), 412 (version), 409 or 422 (domain method). A 404 therefore wins over 412.
- DELETE of a missing resource is 404. A repeated create with a client-supplied id is 409 `already_exists`.
- Batch: 207 even when every item fails. Item status is 201 for batch-create (pass `success_status=201` to `batch_response()`), 204 for batch-delete (`success_status=204`) and 200 otherwise, or the item's error (500 `server.internal_error` for an unexpected failure such as a failed event handler). Only errors that concern the whole request return a 4xx: 415, malformed JSON (400), validation including duplicate ids and over the item limit (422), an item `etag` that is not a single strong ETag (400) or is empty (428), 401, 403, and a lock conflict while processing the whole batch (409). An event chain past the kernel's limits (`EventChainLimitExceededError`) while processing the whole batch fails the whole request with 500 `server.internal_error`; in the item-by-item fallback it is that item's 500.
- 413 and 429 come from the reverse proxy or gateway, not the service.

## Error codes

- Define each domain error in `app/core/<context>/domain/errors.py` as a `@dataclass` subclass of `DomainError` with the class variables `code`, `kind` and `message`; the dataclass fields are the params. See `references/example/app/core/billing/domain/errors.py`.
- Name the class after the business rule it rejects, without an `Error` suffix (`InvoiceAlreadyVoided`); ruff `N818` is ignored for this. The `title` comes from the class name.
- Codes match `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$`, at most 63 characters. Domain codes are `<bounded_context>.<aggregate>.<reason>`. The kernel generates `not_found` and `already_exists` per aggregate and owns the `request`, `validation`, `auth`, `concurrency`, `rate_limit` and `server` codes; never redefine them.
- `message` is an English template whose `{placeholders}` are the lowerCamelCase field names (`invoice_id` → `{invoiceId}`). Params are flat strings, numbers or booleans; never put pre-built English sentences or personal data (email, phone) in them.
- All messages are English; the backend never localizes. Frontends translate by `code` and `params`.
- Codes and their param keys are API contract: never rename, remove or reuse them; adding a code or a key is allowed.
- Unique and foreign key violations: name the constraint through the kernel's naming convention and map it in the repository module with `register_constraint_error("<constraint>", ErrorClass)`. Primary keys register themselves as `already_exists`. Unmapped violations are 500. The port only sees `DomainError`, never `IntegrityError`.
- `make error-catalog` writes `error-catalog.json` (code, status, English title, param keys, and the English message template for `DomainError` subclasses) as the source for frontend translations. Keep the catalog test passing: `references/example/tests/test_error_catalog.py`.

## Naming

- JSON fields and query parameters: camelCase. Paths: kebab-case with plural collections.
- Enum values: lowercase (`active`, `voided`).
- Route function names: verb + resource, unique across the service; the kernel turns them into the camelCase `operationId` (`void_invoice` → `voidInvoice`, `batch_void_invoices` → `batchVoidInvoices`).
- Permissions: `<aggregate>:<action>` in snake_case (`invoice:read`, `invoice:void`); a batch operation reuses the permission of its single operation.
- Files follow the reference layout per aggregate: `<aggregate>_router.py`, `<aggregate>_schemas.py`, `<aggregate>_controller.py`, `<aggregate>_commands.py`, `<aggregate>_repository.py`, `<aggregate>_model.py`, `<aggregate>_use_case.py`.
