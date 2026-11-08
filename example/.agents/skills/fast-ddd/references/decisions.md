# Design decisions

The reasons behind rules that the code alone does not explain. Section numbers refer to the framework's design document (`docs/design.md` in the fast-ddd-service repository).

## Where shared code lives

Place code by who shares it and what it depends on (§6.4); the table is in `references/rules/layering.md`. There is no unlayered `lib/` or `packages/` directory because both predecessors failed with one. A `packages/` directory copied into each service let the copies drift apart, and still held app-specific types. An `app/lib` that imported the settings or business enums broke the rule that adapter never imports `app.settings`, and put domain code outside its bounded context.

Code that only the core of several bounded contexts shares, using nothing beyond stdlib and pendulum, goes in `app/lib` as a layer below `app.core`. It cannot live under `app/core/`: the `bounded-contexts` independence contract treats every `app.core.*` package as a context, so no other context could import it. A uv workspace `packages/` directory is rejected because it sits outside `root_packages`, where neither import-linter nor `fast-ddd-check-packages` looks inside it. Code that other services need belongs in the kernel or in its own versioned distribution, never in a copied directory.

## Why domain events store tracing context

`domain_event` is the permanent record of who did what and when (§7.5). Each row stores `trace_id`, `event_id` and `parent_event_id` (`references/example/app/core/billing/domain/events.py` inherits them from `DomainEvent`) so that a row links to everything else about the same request:

- `trace_id` is the OpenTelemetry trace id (§12.1), so a row can be looked up directly in the tracing system and matched with JSON log lines, which carry the same id.
- `event_id` and `parent_event_id` record causality: which event's handler, or which MQ message, produced this event. They were renamed from the original `span_id`/`parent_span_id` so they are not confused with OpenTelemetry spans.
- Both come from `fast_ddd.context` ContextVars when the event is created. `EventBus.dispatch` sets the parent through `event_scope`, and the MQ wrapper sets it from the message's `eventId`. The original kept them on a module-level use case instance, so concurrent requests overwrote each other and only the first aggregate of a batch got a parent.

Never set these fields by hand and never keep tracing state on a use case or controller. Use cases have no mutable state, which is why controllers and use cases can be module-level singletons.

## When to enable archive snapshots

Archive is off by default: `RepositoryBase.archive_model_class = None` (§7.5). Enable it only on explicit request, for an aggregate that must answer "what was its complete state at time T", such as orders and payments, where a snapshot is direct evidence in disputes and reconciliation. The repository writes a snapshot of the new state after every save that changes the row and of the last state at delete; it never snapshots creation, so the version-1 state lives in the row until the first update and afterwards only in the creation event. `domain_event` cannot replace it: rebuilding state means replaying every event, and event formats evolve (`DomainEvent.VERSION`), so replays are fragile.

The cost is one row per saved change and per delete. The original archived almost every write, and its snapshots also copied an `operation_histories` JSONB array that grew with each change, so storage grew quadratically. Do not store operation history in the aggregate row. It is a domain feature that gets its own table, or is queried from `domain_event` by `aggregate_id`; see `references/recipes/operation-history.md`.

The steps, the archive model's columns and the tests are in `references/recipes/archive-snapshot.md`.

## When to use an event handler instead of calling a use case

Use an in-process event handler, registered in `wire_events(bus)`, when the reaction follows from a domain fact rather than from one entry point (§8.2):

- Outbound I/O: publishing integration messages, as `publish_invoice_event` does, or enqueueing a task for slow external calls, as `enqueue_void_notice` does in `references/example/app/adapter/event_handler/billing/invoice_event_handler.py`. Core never knows about MQ or tasks.
- Changes to another aggregate, or a reaction in another bounded context: core contexts are independent, so the reacting context's adapter handler calls its own controller.
- Work that must commit or roll back with the command: handlers run in the same transaction, before the outermost commit.

Put the logic in the domain method or use case instead when it changes the aggregate the command itself saved. `SessionProvider` protects those aggregates while handlers run (`AlreadySavedInThisCommandError`), because the response and its `ETag` are built from the command's result: a handler changing the same aggregate would make them stale, and the client's next `If-Match` would get 412.

A handler always calls use cases through a controller (`execute()`/`run_batch()`). A direct call would write the new events to `domain_event` without dispatching them, and nothing would report it. A `DomainError` from a handler becomes `EventHandlerFailedError`: a 500 response for a single HTTP command, an item status 500 inside the 207 of a batch (after the item-by-item fallback), and a retry over MQ and in tasks. It is not the command's own business rejection. An event chain past the kernel's limits (`EventChainLimitExceededError`) fails the whole command, and a whole batch without the fallback; only in the fallback of a batch that is its own unit of work does it fail just its item. Handlers of `*Deleted` events use only the event's data; the row is already gone. A fan-out that would lock many rows goes to the `TaskQueue` as one task per chunk instead. A handler with database I/O whose commands run in large batches can receive each dispatch's events as one list: `references/recipes/batch-event-handler.md`.

## Nested SessionProvider use

One `SessionProvider` owns the transaction of a unit of work, and only the outermost scope commits or rolls back (§8.2). Nested `async with provider:` scopes only count depth, and an exception in a nested scope propagates without a rollback. The original rolled back inside nested scopes and committed in `__aexit__` without checking for an exception; neither behavior survives.

`execute()` and `run_batch()` open the outermost scope when none is active. Called from inside one, for example from an event handler or an MQ subscriber, they wrap the call in `provider.savepoint()`. A database error that the adapter turns into a `DomainError` then rolls back only that SAVEPOINT, and the caller can catch it and continue. PostgreSQL aborts the whole transaction after a failed statement, so never catch a database exception in a nested scope without a SAVEPOINT around the failing part.

Rolling back a SAVEPOINT also discards everything registered after it: `after_commit` hooks such as staged MQ messages, the record of saved aggregates, pending events, and the aggregates' `version`/`updated_at`. A batch fallback can therefore save again what the whole-batch attempt saved. `after_commit` hooks run only after the outermost commit, may do I/O only, and log their failures instead of raising them, because the data is already committed. `on_rollback` hooks run after the outermost rollback and open their own transaction. The HTTP middleware creates the provider but opens no transaction. Each top-level `execute()` or `run_batch()` call opens and commits its own transaction, so a route makes one controller call per request. Over MQ and in tasks, the subscriber or task wrapper opens the transaction, and controller calls run inside it as SAVEPOINTs.

## Writing a batch use case

The aggregate stays the consistency boundary; batching changes only I/O and orchestration (§8.2). Domain methods stay single-aggregate and check before they mutate.

- The use case offers a single method (`void`) and a batch method (`void_many`). The batch method calls `apply_batch(repository, Aggregate, items, apply)`: it loads with one locked query in id order, which prevents deadlocks, applies the domain method in memory, collects not-found, version and domain failures per item, and saves the successes with one flush. Batch-create calls `create_batch(repository, items, create)` instead: it runs the factory per item, collects its domain failures, and saves the successes with one flush. An id that already exists fails that flush, and the runner's item-by-item fallback reports it as 409 `already_exists` on that item only. Batch-create, batch-update and batch-delete are recipes: `references/recipes/batch-operations.md`. Never loop over the single method. See `references/example/app/core/billing/use_case/invoice_use_case.py`.
- The controller calls `run_batch(items, batch=..., single=...)`. When the whole batch fails unexpectedly (an `IntegrityError`, a handler failure), the runner rolls back and retries item by item, so each item fails alone. A lock conflict while processing the whole batch fails the request with 409 instead, because retrying item by item would hit the same lock. An `EventChainLimitExceededError` while processing the whole batch fails the request with 500; in the fallback it fails only its item, because each item has committed on its own, unless the batch is nested in a message, task or handler, where it is raised so the enclosing unit of work rolls back.
- Callers without a 207 response (tasks, MQ subscribers, event handlers) pass `raise_on_transient=True`. A transient item failure then rolls back and retries their whole unit of work instead of losing it. Keep at most 100 items in one unit of work: its events count toward one `max_events_per_unit_of_work` and its rows stay locked until it commits. When a message or handler has more items, it enqueues one task per chunk instead, each its own unit of work, following `references/workflows/batch-operation.md` step 5.
- The route rejects duplicate ids with 422 (`ensure_unique_ids`), because their order of execution is undefined. Every item carries its `etag` (batch-create excepted: its items do not exist yet), and the batch reuses the single operation's permission.
- The acceptance test sends the same number of statements for N=1 and N=50. Never write a bulk SQL UPDATE that bypasses the aggregates; it skips domain rules, events and archive.

## Domain command or PATCH

PATCH edits only the content a client decides, such as `InvoiceContent` (§9.2). A state transition or business operation is a domain command (§14.1): its own domain method that checks invariants, its own event, route (`POST /{id}/<verb>`), permission and error codes, as void shows in `references/example/app/core/billing/domain/invoice.py`. Writing a transition as a PATCH of a `status` field moves the domain rule to the client, which is why request models never accept `status`.

A business `status` enum arrives with the first domain command that needs it, together with its transition checks, error codes and events. Default CRUD aggregates have only the technical fields, because DDD defines no default states. Choose void over delete when the record must keep appearing in lists and queries, for example invoice numbers that must stay continuous or records the law requires keeping. Otherwise delete; `domain_event` keeps the audit trail. Add commands only when the user asks for them.

## 409 or 422

If the same request could succeed when the resource were in another state, use 409 (`ErrorKind.CONFLICT`); if it can never succeed, use 422 (`ErrorKind.INVALID`) (§9.5). Examples in `references/example/app/core/billing/domain/errors.py`: `InvoiceAlreadyVoided` is 409; `InvoiceHasNoLines` is 422; `InvoiceNumberTaken` is 409, because the same number becomes valid once the other invoice no longer holds it.

This follows RFC 9110 §15.5.10: a 409 tells the client it can resolve the conflict and resend. Google maps the same case to 400 FAILED_PRECONDITION; this project does not. Related cases keep their own statuses: a version mismatch is 412, not 409; a client-supplied id that already exists is 409 `already_exists`; a lock timeout or deadlock is 409 `concurrency.lock_conflict`, which the client may retry.

The kind also drives MQ behavior: the subscriber wrapper sends `INVALID` errors to the DLQ and acknowledges and skips the other `DomainError` kinds (only `concurrency.lock_conflict` is retried). A wrong kind therefore loses or dead-letters messages, not just HTTP statuses.

## When a repository may use the global tenant scope

Declare `tenant_scope = "global"` only for data that belongs to no organization, such as system settings (§10.2). Such an aggregate has `organization_id = None`, and its events publish `organizationId: null`, which only subscribers registered with `accepts_global=True` receive.

`tenant_scope` has no default and a missing declaration fails at class definition, so every repository states its choice in code. Never use `"global"` to reach organization data across tenants. It removes the BOLA filter for every caller, permanently and silently. Use `system_context("<reason>")` for the specific call instead: it applies only inside the current unit of work, logs every use, and `EventBus` lifts it for handlers, so the reactions still run in their event's organization.

## Why organization_id comes from the aggregate

The aggregate carries its own `organization_id`, and storing, recording events and publishing all read it from there, never from the context (§7.4, §10.2):

- Under `system_context()`, one unit of work may touch several organizations, and the context organization is `None`. Reading the aggregate keeps every `domain_event` row, archive snapshot and MQ `organizationId` correct.
- `AggregateRoot.add_event` copies `organization_id`, `aggregate_type` and `aggregate_id` onto the event, so `save_many` and `integration_message()` need neither a reload nor the context. `EventBus` then sets each handler's tenant from the event, so handlers run in the right organization even when the trigger was cross-tenant.
- Core never reads the organization from the context. The creating use case takes an explicit `organization_id` parameter, which the controller fills from `current_organization_id()`, or the caller passes explicitly under `system_context()`. Core stays free of tenancy plumbing, and unit tests need no context.
- `save_many` cross-checks: under an organization filter, an aggregate whose `organization_id` differs from the current organization is reported as not found, and an `"organization"` aggregate without one is rejected.
