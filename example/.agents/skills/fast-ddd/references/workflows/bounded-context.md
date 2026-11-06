# Add a bounded context

Placeholders: `<context>` is the bounded context name in snake_case (for example `billing`). It prefixes table names (`<context>_<aggregate>`), error codes (`<context>.<aggregate>.<reason>`) and the `bounded_context` ClassVar of every aggregate in it.

## When to use

- The user asks for a new business area whose model, language and rules are separate from the existing contexts, for example billing next to scheduling.
- Not for a new aggregate inside an existing context: use `references/workflows/aggregate.md` directly.
- A context with no aggregate has nothing to test or register. Ask the user for the first aggregate and add it with the aggregate workflow in the same change.

## Files to change

- `app/core/<context>/__init__.py`, `app/core/<context>/domain/__init__.py`, `app/core/<context>/use_case/__init__.py`: empty package markers.
- `app/adapter/controller/__init__.py`: create it if missing (the template has none), then `app/adapter/controller/<context>/__init__.py`.
- `app/adapter/repository/<context>/__init__.py` (`app/adapter/repository/__init__.py` already exists in the template).
- `app/port/restful/__init__.py`: create it if missing, then `app/port/restful/<context>/__init__.py`.
- Only when the request also needs them: `app/adapter/event_handler/__init__.py` and `app/adapter/event_handler/<context>/__init__.py`, `app/port/message_queue/__init__.py` and `app/port/message_queue/<context>/__init__.py`, `app/port/task/__init__.py` and `app/port/task/<context>/__init__.py`. The matching workflows add the modules inside them.
- `tests/core/__init__.py`, `tests/adapter/__init__.py`, `tests/port/__init__.py`: create them if missing; tests import each other as `tests.*` packages.
- `app/wiring.py`, `app/adapter/repository/models.py` and `alembic/versions/` change through the first aggregate (aggregate workflow), not here.
- `.importlinter`: no edit. The `independence` contract lists `app.core.*`, so the new context is covered automatically, and `layers`/`forbidden` contracts already cover `app.core`, `app.adapter` and `app.port`.

## Rules to load

- `references/rules/layering.md`: layer boundaries, why contexts are independent, where shared code goes.
- `references/rules/testing.md`: the tests the first aggregate must bring.

## Reference code

- `references/example/app/core/billing/__init__.py`: the context package; copy the layout `domain/` + `use_case/` under it.
- `references/example/app/core/billing/domain/invoice.py`: `bounded_context: ClassVar[str] = "billing"` and `CustomerId`/`Customer`, a context keeping its own id type and value-object snapshot of another context's data instead of importing it.
- `references/example/app/adapter/controller/__init__.py`: intermediate package marker. Without it import-linter would skip everything below it; `fast-ddd-check-packages` reports the missing file, so `make check` fails.
- `references/example/app/port/restful/__init__.py`: same for the port side.
- `references/example/app/port/message_queue/customer/customer_subscriber.py`: data from another context or service arrives as a message, not as a core import.
- `references/example/app/wiring.py`: where the first aggregate's router and handlers are registered.

## Steps

1. Pick `<context>` with the user. It must match `[a-z][a-z0-9_]*` (lowercase letter first; a merely valid Python identifier such as `Billing` makes every `DomainError` in the context fail at import) and be short: it ends up in table names and error codes (max 63 characters per code).
2. Create the core, adapter and port packages listed above with empty `__init__.py` files, including every intermediate directory that holds only sub-packages (`app/core/<context>/`, `app/adapter/controller/`, `app/port/restful/`, ...). `make check` fails through `fast-ddd-check-packages` and lists the directory when one of them is missing, because import-linter would otherwise skip that whole subtree while its contracts still report "kept".
3. Keep the context independent. Code in `app/core/<context>/` never imports `app.core.<other>`; refer to another context's aggregates by an id `NewType` declared in this context and copy the few attributes you need into a frozen value object. React to another context's changes through a domain event handler (`references/workflows/event-handler.md`) or an MQ subscriber (`references/workflows/mq-consumer.md`).
4. If two contexts need the same pure helper, do not put it under `app/core/` (the independence contract treats every child as a context). Shared core code goes to `app/lib` with its own contract changes; see "Where shared code lives" in `references/decisions.md` and ask the user before adding it.
5. Add the first aggregate with `references/workflows/aggregate.md`. It registers the router in `app/wiring.py`, the model module in `app/adapter/repository/models.py`, creates the migration and the tests.
6. Run `make check` from the service root.

## Required tests

- The context itself adds no test file. Its first aggregate brings the full set from `references/workflows/aggregate.md`: domain unit tests under `tests/core/`, repository integration tests (testcontainers PostgreSQL) under `tests/adapter/`, API tests under `tests/port/` and the error catalog test, following `references/example/tests/core/test_invoice.py`, `references/example/tests/adapter/test_invoice_repository.py`, `references/example/tests/port/test_invoice_api.py` and `references/example/tests/test_error_catalog.py`.
- `make check` checks the package layout: `fast-ddd-check-packages` fails when a directory under `app/` lacks `__init__.py` or has a name that is not a valid Python identifier (`not a valid package name`; rename it, because import-linter skips it even with `__init__.py`) while it or a directory below it contains `.py` files, or when a top-level `app.*` module is in no contract. `lint-imports` then enforces no cross-context import in core.

## Pitfalls

- A missing intermediate `__init__.py` (for example `app/port/restful/__init__.py`) fails `make check` through `fast-ddd-check-packages`; add the empty file rather than moving modules. Below the layer packages (`app/core/`, `app/adapter/`, `app/port/`) the template ships only `app/adapter/repository/__init__.py`.
- Do not add a placeholder aggregate or empty router just to make the context visible; the empty template already passes every contract.
