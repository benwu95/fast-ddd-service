# Layering rules

Source: design §6. Enforced by import-linter with the service's `.importlinter` and by the kernel's contract coverage check `fast-ddd-check-packages`; both run in `make imports`, which `make check` includes. Fix the import that breaks a contract; never loosen the contract.

## Layers

Dependencies point inward: `app.port` → `app.adapter` → `app.core`.

| Layer | Holds | May use | Must not use |
|---|---|---|---|
| `app/core/<context>/domain/` | aggregates (`AggregateRoot` subclasses), value objects, domain events, `DomainError` subclasses, repository Protocols | stdlib, pendulum, `fast_ddd` | Pydantic, SQLAlchemy, FastAPI, FastStream, `fast_ddd_adapter`, `fast_ddd_port`, `app.settings` |
| `app/core/<context>/use_case/` | use cases | same as domain | same as domain |
| `app/adapter/` | controllers and command dataclasses, repositories and ORM models, event handlers, outbound clients | SQLAlchemy, `fast_ddd_adapter`, `fast_ddd` | FastAPI, `fast_ddd_port`, `app.settings` |
| `app/port/` | `restful/` routers and schemas, `message_queue/` subscribers, `task/` task handlers | FastAPI, FastStream, Pydantic, `fast_ddd_port`, controllers | `app.adapter.repository` |

What each layer does:

- Domain: value objects are `@dataclass(frozen=True, slots=True)`; each aggregate has its own id `NewType` over `UUID`; domain methods check invariants first, then change state and call `add_event`. See `references/example/app/core/billing/domain/invoice.py`.
- Use case: a plain class without mutable state that receives its repository Protocol (`references/example/app/core/billing/domain/repository.py`) in the constructor. It never opens a transaction, dispatches events or reads the organization from context. See `references/example/app/core/billing/use_case/invoice_use_case.py`.
- Controller: a plain class; every method wraps the use case call in `execute()` or `run_batch()` from `fast_ddd_adapter.controller`, takes the doer from `current_user()` and the organization from `current_organization_id()`, accepts command dataclasses (`@dataclass(frozen=True, slots=True)`) instead of port models, and returns domain objects. See `references/example/app/adapter/controller/billing/invoice_controller.py` and `references/example/app/adapter/controller/billing/invoice_commands.py`.
- Repository: subclasses `RepositoryBase` with hand-written `model_to_entity`/`entity_to_model`. See `references/example/app/adapter/repository/billing/invoice_repository.py`. Register every module that defines ORM models in `app/adapter/repository/models.py`.
- Port: converts `RequestModel` to a command field by field and builds each `ResponseModel` with a hand-written `from_domain()`. HTTP routes, MQ subscribers, task handlers and in-process event handlers all reach use cases only through a controller. Over HTTP a direct use case call fails with `SessionNotActiveError` (500) because no transaction is open. Inside an MQ subscriber, a task handler or an event handler, a direct call writes its events to `domain_event` without dispatching them, and nothing reports it.

Modules outside the layers form the composition root: `app/settings.py`, `app/bootstrap.py`, `app/wiring.py`, `app/main.py`, `app/consumer.py`, `app/task_worker.py`. Register everything explicitly in `app/wiring.py` (see `references/example/app/wiring.py`): `wire_resources(settings)` for outbound clients, `wire_events(bus)` with `bus.subscribe(EventType, handler)`, `wire_http(app)` for routers, `wire_consumer(broker, session_factory)` for subscribers (returns the queue names), `wire_tasks(registry)` for tasks and schedules. Never register through import-time decorators.

## Dependency rules

Contracts in `.importlinter` (`include_external_packages = True`, `unmatched_ignore_imports_alerting = error`):

| Contract | Rule |
|---|---|
| `layers` | `app.port` > `app.adapter` > `app.core`; a lower layer never imports a higher one |
| `core` | `app.core` must not import `fast_ddd_adapter`, `fast_ddd_port`, `pydantic`, `sqlalchemy`, `fastapi`, `faststream`, `app.settings` |
| `adapter` | `app.adapter` must not import `fast_ddd_port`, `fastapi`, `app.settings` |
| `port` | `app.port` must not import `app.adapter.repository`; reaching it indirectly through a controller is allowed |
| `bounded-contexts` | the packages under `app.core.*` are independent of each other |
| `composition` | `app.core`, `app.adapter`, `app.port` must not import `app.bootstrap`, `app.wiring`, `app.main`, `app.consumer`, `app.task_worker` |
| `task-queue` | `app.core`, `app.adapter`, `app.port` must not import `pgqueuer`; use the kernel's `TaskQueue` through `task_queue()` |

- The kernel ships one top-level package per layer so these contracts can see it: `fast_ddd` (core), `fast_ddd_adapter`, `fast_ddd_port`. `fast_ddd_devtools` is development tooling; import it only from tests.
- Give adapter code its settings values in `wire_resources(settings)` through constructors and keep the objects in `app/adapter/resources.py` behind typed getters (`references/example/app/adapter/resources.py`). `app.settings` inherits `KernelSettings` from `fast_ddd_port`, so importing it from adapter breaks the `adapter` contract twice: once for `app.settings` and once, indirectly, for `fast_ddd_port`.
- `UNSET` lives in `fast_ddd_adapter.commands` on purpose: the `core` contract keeps "not sent" out of the domain.
- Bounded contexts never import each other's core. One context reacts to another through an adapter event handler that calls its own controller.
- `fast-ddd-check-packages` fails when a directory under `app/` lacks `__init__.py` while it or any directory below it contains `.py` files, or when a top-level module of `app` appears in no contract. This covers intermediate directories that hold only subpackages, such as `app/core/<context>/`: without their `__init__.py`, import-linter would silently skip everything below them and still report every contract as kept. `.py` files under `__pycache__` or a directory whose name starts with `.` do not count.
- Never import from `references/example/`; copy its patterns into this service's own modules.

## Shared code

Place code by who shares it and what it depends on. Never create an unlayered `lib/`, `packages/` or `utils/` catch-all.

| Shared by | Depends on | Location |
|---|---|---|
| several services | DDD infrastructure | the kernel; request the change in the framework |
| several services | business logic or a third-party integration | a separate repository and versioned distribution |
| this service | SQLAlchemy, httpx2, a third-party SDK | a capability subpackage of the layer that owns the dependency, such as `app/adapter/<capability>/` or `app/port/<capability>/`; see `references/example/app/adapter/notification/notification_client.py` |
| the core of several bounded contexts here | only stdlib and pendulum | `app/lib`, a layer below `app.core` |
| one bounded context | anything in that context's domain | that context's package |

Adding `app/lib` needs all of these `.importlinter` changes in the same change. `fast-ddd-check-packages` fails only while `app.lib` appears in no contract, so it does not catch a partial change:

- Append `app.lib` as the lowest entry of the `layers` contract: `app.port` > `app.adapter` > `app.core` > `app.lib`.
- Add `app.lib` to the `source_modules` of the `core`, `composition` and `task-queue` contracts, so it has the same limits as `app.core`.
- Never put it under `app/core/`: the `bounded-contexts` contract would treat it as a context that no other context may import.

Do not add a uv workspace `packages/` directory: it sits outside `root_packages`, so no contract or coverage check sees it. Code that other services need moves to its own repository instead.
