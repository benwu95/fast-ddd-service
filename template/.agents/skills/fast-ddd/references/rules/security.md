# Security rules

Source: design §10 (OWASP API Security Top 10 2023). The kernel enforces most of this; services must not bypass it.

## Tenant isolation

- Aggregate ORM models inherit `AggregateModel`, which carries `organization_id`. Every composite index and organization-level unique constraint starts with `organization_id` (for example `uq_billing_invoice_organization_id_number`).
- Every `RepositoryBase` subclass declares `tenant_scope: ClassVar[TenantScope]` as `"organization"` or `"global"`. There is no default; a missing declaration raises `TypeError` when the class is defined. See `references/example/app/adapter/repository/billing/invoice_repository.py`.
- With `"organization"`, `load_many`, `load`, `search` and `save_many` filter by the current organization. Every custom query adds `*self.tenant_conditions()` to its `where()`, as `active_ids_of_customer` and `totals_since` do in the reference repository.
- Another organization's row is indistinguishable from a missing one: 404, and a missing item in a batch. Never return 403 for it (BOLA).
- An `"organization"` repository used without an organization in context and outside `system_context()` raises `TenantContextMissingError` (500). Never work around it by returning empty results.
- Creating an aggregate: the use case takes an explicit `organization_id` parameter and passes it to the factory. The controller fills it from `current_organization_id()` and raises `TenantContextMissingError` when it is `None`; core never reads the organization from context.
- After creation, the organization always comes from the aggregate. `add_event` copies it to each event, so `domain_event` rows and MQ `organizationId` stay correct.
- Where the tenant context comes from: HTTP from the JWT organization claim (unit-of-work middleware); MQ from the message's `organizationId` (subscriber wrapper); an in-process event handler from the event's `organization_id` (`EventBus` sets it and cancels any `system_context()` exemption); a task from the `organization_id` given to `task_queue().enqueue()`. Tests build the same context with `unit_of_work_scope(session_factory, user=..., organization_id=...)` from `fast_ddd_adapter.testing`.
- Cross-tenant work uses `with system_context("<reason>"):` from `fast_ddd_adapter.infrastructure`. It only lifts tenant filtering inside the current unit of work, logs a warning on every use, and creates no session. Keep the block as small as the cross-tenant read, then work per organization with an explicit `organization_id`; see `enqueue_daily_summaries` in `references/example/app/adapter/controller/billing/invoice_controller.py`. Scheduled tasks have no organization context and follow the same pattern.
- Global events (`organizationId` is `null`) reach only subscribers registered with `accepts_global=True`. Their handlers may touch only `"global"` repositories or must run inside `system_context()`.
- Request models never accept `organizationId`, `status`, `doer` or `creator`. `RequestModel` sets `extra="forbid"`, so an unknown field is 422 (BOPLA); create may accept a client `id`. Response models list every returned field explicitly.
- Bound resource use: `limit` at most `MAX_BATCH_ITEMS`, bounded `offset`, batches at most `MAX_BATCH_ITEMS`, bounded `searchKey` count and length, `max_length` on strings and lists. Body size and rate limits belong to the gateway.
- Required tests: the repository test proves another organization cannot read the data (`references/example/tests/adapter/test_invoice_repository.py`); the API test proves another organization gets 404 (`references/example/tests/port/test_invoice_api.py`).

## Authentication and authorization

- The kernel's unit-of-work middleware verifies the JWT before the router runs and then sets the user and organization context. Services write no token handling. Paths without authentication come from `public_paths` in settings (health and OpenAPI by default).
- JWT settings (`JwtSettings`): `issuer`, `audience`, `jwks_url`, `user_id_claim`, `organization_id_claim`, `permissions_claim` and `permissions_format` have no defaults; the service fails to start without them. Keys come from the JWKS URL; the kernel verifies `iss`, `aud`, `exp` and `nbf` and accepts only the `algorithms` whitelist (RS256 and ES256 by default).
- Failures return 401 with `WWW-Authenticate: Bearer` (`auth.unauthenticated`), or with `error="invalid_token"` (`auth.token_invalid`, `auth.token_expired`).
- Every route declares one permission with `dependencies=[require("<aggregate>:<action>")]` from `fast_ddd_port.auth`; a missing permission is 403 `auth.permission_denied`. Actions: `read`, `create`, `update`, `delete`, and the domain command's verb (`void`). A batch reuses its single operation's permission (`batch-void` needs `invoice:void`).
- User and organization come only from the token, never from the path, query or body.
- Tokens travel in `Authorization: Bearer`, not cookies, so no CSRF protection is needed; switching to cookies requires CSRF protection and `SameSite` together.
- CORS origins are listed explicitly in `cors_allow_origins`; never `*`.
- A 500 never returns exception content; the middleware logs it with the trace id. Never log tokens, passwords or other secrets.
- In tests, sign tokens with `TokenFactory` from `fast_ddd_port.testing` and an offline JWKS; see `references/example/tests/port/conftest.py`. API tests cover 401 and 403 (see `test_authentication_and_permissions` in `references/example/tests/port/test_invoice_api.py`, which checks one route of each) and assert that each route rejects a token without its own permission.
