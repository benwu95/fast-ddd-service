# Add a background task or a cron schedule

## When to use

- Work this service triggers itself that must run asynchronously and must not be lost: external calls that need backoff retries, exports larger than the synchronous limit of `references/recipes/export.md`, imports, delayed work, or a large fan-out split into one task per chunk (`references/workflows/batch-operation.md` step 5).
- Periodic work (a cron schedule) that the worker process runs.
- Not for integration with other services; use `references/workflows/mq-consumer.md` to consume and `references/workflows/event-handler.md` to publish.

## Files to change

- `app/adapter/controller/<context>/task_names.py`: task and schedule name constants. They live in the adapter because both the adapter event handler (enqueue) and the port (registration) import them.
- `app/port/task/<context>/<aggregate>_tasks.py`: payload models, task handlers and `register(registry: TaskRegistry)`.
- `app/port/task/__init__.py` and `app/port/task/<context>/__init__.py`: empty package markers; the template ships neither, so create both. `fast-ddd-check-packages` reports either one when it is missing, so `make check` fails until both exist.
- `app/adapter/controller/<context>/<aggregate>_controller.py`: the controller methods that do the work and, for cron or a bulk message, the fan-out.
- `app/adapter/event_handler/<context>/<aggregate>_event_handler.py`: the handler that enqueues the task from a domain event (see `references/workflows/event-handler.md`).
- `app/wiring.py`: call `<aggregate>_tasks.register(registry)` from `wire_tasks`. The template names the unused parameter `_registry`; rename it to `registry`.
- For a new external service: `app/adapter/<client>/__init__.py` and `app/adapter/<client>/<client>_client.py`, a field in `Resources` in `app/adapter/resources.py`, its URL and timeout in `Settings` in `app/settings.py`, and construction plus closer in `wire_resources` in `app/wiring.py`, renaming the template's unused `_settings` parameter to `settings`.
- With a new required `Settings` field, extend the service-owned root test fixtures, because `settings()` in the template-owned `tests/runtime/support.py` would otherwise raise `ValidationError`. In `tests/conftest.py`, add an autouse fixture that sets the variable with `monkeypatch.setenv` (`reference_service_settings` in `references/example/tests/conftest.py`), and build the client on `httpx2.MockTransport` with `configure_resources(...)` in the `infrastructure` fixture. In `tests/support.py`, add the fake service (`NotificationService` in `references/example/tests/support.py`). Never edit `tests/runtime/`.
- `tests/port/test_<aggregate>_tasks.py`, and `tests/port/__init__.py` if missing.

## Rules to load

- `references/rules/layering.md`
- `references/rules/time-and-serialization.md`
- `references/rules/security.md`
- `references/rules/testing.md`

## Reference code

- `references/example/app/adapter/controller/billing/task_names.py`: `SEND_VOID_NOTICE`, `SEND_DAILY_SUMMARY`, `DAILY_SUMMARY_SCHEDULE`, `VOID_INVOICES`.
- `references/example/app/port/task/billing/invoice_tasks.py`: payload models, handlers and `register` with `registry.task` and `registry.cron`.
- `references/example/app/adapter/controller/billing/invoice_controller.py`: `send_void_notice`, `enqueue_daily_summaries` (cron fan-out) and `send_daily_summary`; `enqueue_customer_invoice_voids` (message fan-out, one task per chunk of ids) and `void_invoices`.
- `references/example/app/adapter/event_handler/billing/invoice_event_handler.py`: `enqueue_void_notice` enqueues from `InvoiceVoided`.
- `references/example/app/adapter/notification/notification_client.py`: external client that is idempotent by a caller-chosen key.
- `references/example/app/adapter/resources.py`, `references/example/app/settings.py` and `references/example/app/wiring.py`: `Resources`, `notification_url`, `wire_resources` and `wire_tasks`.
- `references/example/app/adapter/repository/billing/invoice_repository.py`: `organizations_issuing_since`, run inside `system_context()`.
- `references/example/tests/port/test_invoice_tasks.py`: the required task and cron tests, with the `drain` and `jobs` helpers.
- `references/example/tests/conftest.py`: `infrastructure` fixture with `PgQueuerTaskQueue` and a fake external service.

## Steps

1. Add the name constants to `task_names.py`, prefixed by the context (`"<context>.<verb_noun>"`). The name is persisted in queued jobs; never rename one that may still be queued.
2. Define the payload as a `fast_ddd_port.models.MessageModel` subclass with snake_case fields (use `Timestamp` for times). Enqueue it as a camelCase JSON mapping, with times from `format_datetime`.
3. Write the handler as `async def <task>(_: TaskEnvelope, data: <Payload>) -> None` and make it call one controller method. The kernel wrapper opens the unit of work with the organization from the job, user `task:<name>` and the trace context; never open a transaction in the handler.
4. Register in `register(registry)`: `registry.task(<TASK>, <Payload>, <handler>)` and `registry.cron(<SCHEDULE>, "<cron expression>", controller.<fan_out_method>)`. Call it from `wire_tasks` in `app/wiring.py`; only `app/task_worker.py` builds the registry.
5. Enqueue from an adapter event handler with `await task_queue().enqueue(<TASK>, {...}, organization_id=event.organization_id)`. It runs in the command's transaction, so the job commits or rolls back with the business data. A controller method may also enqueue inside its `execute(...)` to fan out a cron run or a bulk message (`enqueue_daily_summaries`, `enqueue_customer_invoice_voids`). Core never enqueues.
6. For a cron schedule, the handler takes no arguments and runs with no organization. Inside one `execute(...)`, enumerate the organizations explicitly with a repository query wrapped in `with system_context("<reason>"):`, then enqueue one task per organization with `organization_id=<org>` and a `dedupe_key` such as `f"{TASK}:{organization_id}:{since.date()}"`. Keep the system context around the query only; the per-organization work runs in the task with tenant filtering on. The `dedupe_key` blocks a duplicate only while the earlier job is still queued or running (`enqueue` returns `False`); once that job has finished or failed, the same key is accepted again, so the per-organization task must stay idempotent.
7. Make every handler idempotent: a job may run more than once. For external calls pass a deterministic idempotency key (the example `PUT`s `/notifications/invoice-voided-{invoice.id}`), so a retry after a remote success and a local commit failure repeats the same request.
8. Let errors propagate. In a task, a `DomainError` from the controller call (for example the target was deleted) or a payload that fails validation fails the job once, without retry. `LockConflict` and other exceptions retry with exponential backoff (`RetryPolicy`: default 3 retries after 5 s, 10 s and 20 s), then the job is held as failed. Other exceptions include `EventHandlerFailedError`, which wraps a `DomainError` raised by a domain event handler. A cron run is never retried: the exception is logged and the schedule runs again at its next tick, so the fan-out must be safe to repeat.
9. When the frontend must see progress, keep the status in a domain aggregate created in the same transaction as the enqueue; the queue tables are internal.
10. Run `make check` from the service root.

## Required tests

Use the PostgreSQL testcontainer and the real `wire_tasks`, draining a worker built with `build_worker`, as in `references/example/tests/port/test_invoice_tasks.py`:

- An enqueue inside a transaction that rolls back leaves no job (`test_rolled_back_void_enqueues_nothing`).
- A deterministic error (`DomainError`) marks the job failed without retry, and a transient error is retried, then marked failed (`test_missing_invoice_fails_once_and_unavailable_service_is_retried`).
- Running the same task twice gives the same result and sends the same idempotency key (`test_void_notice_is_sent_and_is_idempotent`, `test_external_success_then_local_commit_failure_resends_the_same_notification_key`).
- For cron: the fan-out enqueues one task per organization, a second run while those jobs are still queued is deduplicated, and each task works only on its organization's data (`test_daily_summary_fans_out_per_organization`, `test_due_daily_summary_runs_in_full_worker_and_keeps_organization_fanout`).
- For a bulk message fan-out: each chunk of ids becomes one task with the camelCase payload (`test_customer_invoices_are_enqueued_in_chunks`).
- `wire_tasks` registers every task name and schedule (`test_worker_registers_tasks_and_the_schedule`).
