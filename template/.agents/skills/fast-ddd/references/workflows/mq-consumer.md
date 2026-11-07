# Consume messages from another service

## When to use

- Another service publishes an integration event (RabbitMQ, the envelope `eventId`, `eventName`, `eventVersion`, `organizationId`, `occurredAt`, `data`) and this service must react to it.
- Not for this service's own domain events; use `references/workflows/event-handler.md`.
- Not for work this service triggers itself and must not lose; use `references/workflows/background-task-and-cron.md`.

## Files to change

- `app/port/message_queue/<source>/<source>_subscriber.py`: exchange and queue constants, the `MessageModel` payload, the handler, and `register(broker, session_factory) -> list[str]`. `<source>` names the publishing side (the example uses `customer`).
- `app/port/message_queue/__init__.py` and `app/port/message_queue/<source>/__init__.py`: empty package markers; the template ships neither, so create both. `fast-ddd-check-packages` reports either one when it is missing, so `make check` fails until both exist.
- `app/adapter/controller/<context>/<aggregate>_controller.py`: the controller method the handler calls, plus any repository query it needs.
- `app/wiring.py`: return the queue names from `wire_consumer`; with several subscriber modules, concatenate their lists. The template names the unused parameters `_broker` and `_session_factory`; rename the ones you use to `broker` and `session_factory`.
- `tests/port/test_<source>_subscriber.py`, and `tests/port/__init__.py` if missing.
- No new settings: `rabbitmq_url` comes from `KernelSettings`.

## Rules to load

- `references/rules/layering.md`
- `references/rules/time-and-serialization.md`
- `references/rules/security.md`
- `references/rules/testing.md`

## Reference code

- `references/example/app/port/message_queue/customer/customer_subscriber.py`: payload model, handler and `register` with `subscribe(...)` and `kernel_queue(...)`.
- `references/example/app/adapter/controller/billing/invoice_controller.py`: `enqueue_customer_invoice_voids` enqueues one `billing.void_invoices` task per chunk of the customer's invoices; `void_invoices` runs one chunk in that task with `run_batch(..., raise_on_transient=True)`.
- `references/example/app/port/task/billing/invoice_tasks.py`: `VoidInvoicesData` and the `void_invoices` task handler.
- `references/example/app/wiring.py`: `wire_consumer` returns the queue names for DLQ declaration.
- `references/example/tests/port/test_customer_subscriber.py`: RabbitMQ testcontainer, `broker` fixture, `envelope`, `dead_letters` and `processed` helpers.
- `references/example/tests/conftest.py`: PostgreSQL testcontainer and the `infrastructure` fixture.

## Steps

1. Define the payload as a `fast_ddd_port.models.MessageModel` subclass with snake_case fields; it validates camelCase aliases and ignores unknown fields. It describes only `data`; the kernel's `Envelope` validates the outer fields.
2. Write the handler as `async def handle_<event>(_: Envelope, data: <Payload>) -> None` (name the first argument `envelope` only when the handler reads it; an unused named argument fails ruff `ARG001`) and make it call one controller method. The port never imports a repository and never calls a use case directly. Create the controller once at module level, as the example does.
3. Register it in `register` with `subscribe(broker, name=<QUEUE>, queue=kernel_queue(<QUEUE>, routing_key="<EventName>"), exchange=<EXCHANGE>, payload=<Payload>, handler=..., session_factory=session_factory)` and return `[<QUEUE>]`. Name the queue `<this-service-context>.<event-kebab-case>`; it is also the inbox key, so never rename it after deployment.
4. Do not add transaction, inbox, ack, retry or DLQ code. The kernel wrapper sets the context (organization from `organizationId`, user `consumer:<name>`, parent event from `eventId`), opens the outermost transaction, claims the `(subscriber, eventId)` inbox row, calls the handler, commits, sends staged messages and acks.
5. Know the outcomes the wrapper applies to what escapes the handler: an invalid envelope or payload, a missing `organizationId` or a malformed `x-retry-count` header goes to `<queue>.dlq` without retry; a `DomainError` from the controller call rolls back the handler's writes and the inbox row, then `INVALID` goes to the DLQ and the other kinds are acked and skipped; `LockConflict` (a `CONFLICT` `DomainError` that is caught first) and every other exception are retried `max_retries` times (default 3), then dead-lettered. Other exceptions include `EventHandlerFailedError`, which wraps a `DomainError` raised by a domain event handler, and `TransientBatchFailureError` from `run_batch(..., raise_on_transient=True)`.
6. A null `organizationId` is a global event. It is acked and skipped unless you pass `accepts_global=True`; then the controller may touch only `tenant_scope = "global"` repositories or run inside `system_context()`.
7. Make the handler safe to reprocess after a retry and keep its unit of work bounded; internal calls pass `expected_version=None`. When bulk work has no upper bound, the handler only reads the ids and enqueues one task per chunk; follow `references/workflows/batch-operation.md` step 5 for the chunk size, the payload and what each task does. The message is acked once the tasks are enqueued, and a failed chunk is retried by its task, not by redelivering the message. Events raised in the task carry the task's context: user `task:<name>` and no parent event; the trace id carries over.
8. Call the subscriber's `register` from `wire_consumer` in `app/wiring.py`. Only `app/consumer.py` calls `wire_consumer`, and after startup it declares a DLQ for each returned queue name; a queue left out of the returned list gets no DLQ, so its rejected messages are dropped. Never register subscribers in the API process.
9. Run `make check` from the service root.

## Required tests

Use a real RabbitMQ testcontainer and the real `wire_consumer`, as in `references/example/tests/port/test_customer_subscriber.py`:

- An invalid payload and a message without `organizationId` both land in the DLQ, and nothing is recorded in the inbox (`test_unusable_messages_go_to_the_dead_letter_queue`).
- Unknown fields in `data` are ignored (the `addedLater` field in `test_deactivated_customer_has_its_invoices_voided_once`).
- The same `eventId` sent twice is processed once: one `ProcessedMessage` row and one set of writes (same test).
- Tenant isolation: data of other organizations is untouched (same test).
- Bulk work enqueued as tasks: wait until the message is processed, assert that nothing has changed yet and the expected tasks are queued, then drain a worker (`drain` in `references/example/tests/port/test_invoice_tasks.py`) and assert the result and the events per unit of work (`test_invoices_past_the_event_limit_are_voided_one_chunk_per_unit_of_work`).
- A handler that writes data and then raises a `DomainError` leaves neither the writes nor the inbox row behind. The example has no such case; write one by making the controller raise after a write and asserting both the data and `processed(...) == 0`.
