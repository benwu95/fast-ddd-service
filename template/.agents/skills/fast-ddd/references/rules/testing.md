# Testing rules

Source: design §8.3 and §13. `make check` runs `kernel-version`, `lockcheck`, `lint` (ruff format check and lint), `typecheck` (pyright strict), `imports` (import-linter and `fast-ddd-check-packages`) and `test` (pytest under coverage). A workflow is done only when `make check` passes. `make format` fixes formatting and auto-fixable lint findings.

## Required tests per aggregate

`make check` also passes when these tests are missing, so every workflow generates them with the code.

| Category | Must cover | Reference |
|---|---|---|
| Domain unit tests | the success path of every domain method; each violated invariant raises its `DomainError`; with a `status`, every allowed and rejected transition | `references/example/tests/core/test_invoice.py` |
| Repository integration tests (testcontainers PostgreSQL) | mapping round trip including child collections; changing only a child entity still increments `version`; tenant filtering (another organization reads nothing); the fixed lock order of `load_many`; `version` and `updated_at` updated and written back | `references/example/tests/adapter/test_invoice_repository.py` |
| API tests | every applicable status code and error code from `references/rules/api.md`; BOLA (another organization gets 404); ETag (missing 428, mismatch 412, unacceptable format 400, 404 before 412); a non-JSON Content-Type gets 415; PATCH semantics of omitted fields, `null` and nested value objects; with a batch operation, the per-item results of the 207 | `references/example/tests/port/test_invoice_api.py`, `references/example/tests/port/test_invoice_http_contract.py`, `references/example/tests/port/test_invoice_etag_limits.py` |
| MQ consumer tests (when a subscriber exists) | failed payload validation and a missing `organizationId` go to the DLQ; unknown fields are ignored; a repeated `eventId` is processed once; a `DomainError` raised after the handler wrote data rolls back both the writes and the inbox | `references/example/tests/port/test_customer_subscriber.py` (the DomainError rollback case has no reference: write a handler that saves and then raises a non-`INVALID` `DomainError`, and assert that neither the write nor a `processed_message` row remains) |
| Background task tests (when a task handler exists) | a task enqueued in a transaction that rolls back is not enqueued; deterministic errors are not retried, transient errors are retried and then marked failed; running the same task twice gives the same result | `references/example/tests/port/test_invoice_tasks.py` |
| Error catalog | code format and uniqueness; message placeholders match params; every service `DomainError` subclass is in the catalog | `references/example/tests/test_error_catalog.py` |

A batch use case also needs a round-trip test: N=1 and N=50 send the same number of statements, measured with `count_statements(engine)` from `fast_ddd_adapter.testing`. See `test_batch_void_round_trips_do_not_grow_with_the_batch` in `references/example/tests/adapter/test_invoice_controller.py`. The condition holds only when the related event handlers do no database I/O, or receive each dispatch's events as one list (`references/recipes/batch-event-handler.md`).

Place tests by layer like the reference: `tests/core/`, `tests/adapter/`, `tests/port/`, each with an `__init__.py` (the template ships only `tests/__init__.py` and `tests/runtime/`).

## Test infrastructure

- Shared fixtures go in `tests/conftest.py`, port fixtures in `tests/port/conftest.py`, and test doubles and builders in `tests/support.py`. The template ships `tests/conftest.py` and `tests/support.py` empty; build all three from `references/example/tests/conftest.py`, `references/example/tests/port/conftest.py` and `references/example/tests/support.py`. When wiring adds a required `Settings` field, extend the root fixtures in the same change: set it with an autouse `monkeypatch.setenv` fixture in `tests/conftest.py`, as `reference_service_settings` does for `NOTIFICATION_URL`. Otherwise `tests/runtime/` cannot build `Settings`.
- The database is a session-scoped testcontainers `PostgresContainer` (`postgres:18`, `driver="asyncpg"`). Build its schema with the Alembic migrations (`command.upgrade(config, "heads")`), never with `metadata.create_all`, so every run tests the migrations. Call `add_kernel_versions(config)` on any `Config` a test builds; `env.py` alone does not add the kernel migrations.
- Isolate tests by truncating tables after each test (the `session_factory` fixture). Add every new table to its truncate list.
- The `infrastructure` fixture configures the kernel as `build_runtime` does, with fakes at the process edge: `configure(session_factory=..., event_bus=..., publisher=RecordingPublisher(), task_queue=PgQueuerTaskQueue())`, `wire_events(bus)`, and outbound HTTP clients on `httpx2.MockTransport`.
- Adapter tests run inside `unit_of_work_scope(session_factory, user=..., organization_id=...)` from `fast_ddd_adapter.testing`. API tests use the real app from `build_app(runtime, tokens.verifier())` through `httpx2.ASGITransport`, with tokens from `TokenFactory`.
- Docker must be running. Tests that need an external tool fail when it is missing; never mark them `skip` or `skipif`.
- `pytest.ini` sets `filterwarnings = error`: every warning fails the test. Exclude a third-party warning only with a narrowly scoped filter; fix your own.
- `asyncio_mode = auto` with session-scoped loops: write `async def test_...` without asyncio markers.
- pyright strict includes `tests`. `# type: ignore` is disabled (`enableTypeIgnoreComments: false`, `reportUnnecessaryTypeIgnoreComment: error`); fix the types instead.
- Coverage: `.coveragerc` measures `app` with branch coverage and `concurrency = greenlet, thread` (without it, code after a database await is reported as uncovered). `fail_under` comes from the Copier answer `coverage_minimum` (80–100); never lower it.
- Migrations: register new ORM modules in `app/adapter/repository/models.py`, then run `make migration name="<message>"` (it adds `--head service@head` and `--version-path alembic/versions`) and review the generated, date-prefixed revision. `tests/runtime/test_migrations.py` checks that the kernel and service branches have one head each, that the models have no pending migration (`alembic check`), and that the service branch downgrades and upgrades.
