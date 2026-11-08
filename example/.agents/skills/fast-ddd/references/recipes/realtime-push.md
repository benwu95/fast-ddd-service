# Recipe: realtime push

Placeholders as in `references/workflows/event-handler.md`. Add this only when the user asks to push changes to frontends as they happen. The kernel provides the transport, authentication, rooms and after-commit delivery in the `realtime` extra (design §14.3); this recipe wires them into the service and decides the rooms.

## When to use

- A frontend must learn about changes without polling: a detail view refreshes when its resource changes, a user is told that their own job finished.
- The push follows a domain event, like an integration message: an adapter event handler decides what to push, after the commit. Core never knows about pushes.
- Not for other services (publish integration messages) and not for anything that must not be lost: a push that fails after the commit is only logged.

## Files to change

- `pyproject.toml` and `uv.lock`: change the dependency to `fast-ddd-kernel[realtime]`, add `wsproto>=1.2` (uvicorn needs a WebSocket implementation), and add `python-socketio[asyncio-client]>=5.18,<5.19` to the dev group for the tests. The extra pins python-socketio below 5.19; keep the client on the same minor version.
- `app/wiring.py`: create, configure and close the emitter in `wire_resources(settings)`.
- `app/main.py`: mount the endpoint in `build_app`, which already receives the runtime and the `JwtVerifier`, and close it with the runtime.
- `app/adapter/event_handler/<context>/<aggregate>_event_handler.py`: the push handlers and their `bus.subscribe` lines.
- `.importlinter`: add `socketio` to the `forbidden_modules` of the `core` contract.
- `typings/socketio/__init__.pyi`: stubs for the Socket.IO client the tests use; python-socketio ships no type information, and pyright strict reports every client call without them. pyright reads `typings/` by default.
- `tests/port/test_<aggregate>_realtime.py`, a recording emitter in `tests/support.py`, and the `infrastructure` fixture in `tests/conftest.py` that configures it.

## Rules to load

- `references/rules/layering.md`: handlers in adapter, mounting in the composition root, `app.adapter` never imports `app.settings`.
- `references/rules/security.md`: tenant and user only from the token, one permission per resource.
- `references/rules/time-and-serialization.md`: push data is camelCase JSON with RFC 3339 timestamps.
- `references/rules/testing.md`: test infrastructure and Docker.

## Reference code

- `references/example/app/adapter/event_handler/billing/invoice_event_handler.py`: an event handler that sends after the commit (`publish_after_commit`); a push handler has the same shape with `push_after_commit`.
- `references/example/app/wiring.py`: `wire_resources` creates outbound resources and returns their closers.
- `references/example/tests/conftest.py`: the `infrastructure` fixture, where a recording emitter replaces the real one.
- `references/example/tests/port/test_invoice_api.py`: HTTP commands and `infrastructure.publisher` assertions, the pattern the push tests follow.

## Steps

1. Emitter, all three roles: in `wire_resources(settings)`, `emitter = create_realtime_emitter(settings.rabbitmq_url, service=settings.service_name)` and `configure_realtime(emitter)` from `fast_ddd_adapter.realtime`, then return `emitter.close` among the closers. `rabbitmq_url` is optional in the settings type; raise `ValueError` when it is `None`, as `build_runtime` does. The API, the consumer and the worker all push through this write-only emitter.
2. Endpoint, API only: in `build_app`, after `wire_http(app)`, call `realtime = mount_realtime(app, verifier=verifier, resources={"<aggregate>": "<aggregate>:read"}, rabbitmq_url=..., service=runtime.settings.service_name, cors_allowed_origins=runtime.settings.cors_allow_origins or None)` from `fast_ddd_port.realtime`, and `runtime.closers.append(realtime.close)`. `service` must be the same name the emitter uses; services sharing a broker never see each other's pushes. The endpoint serves WebSocket only at `/realtime/socket.io`. `None` allows the same origin only; behind a TLS proxy the proxy must send `X-Forwarded-Proto`.
3. Resources: `resources` maps each joinable resource name (lower snake_case, usually the aggregate) to the permission `require()` checks for reading it over HTTP. A client joins with `join` and `{"resource": "<aggregate>", "id": "<uuid>"}` and gets the ack `{"status": "ok" | "error", "data": ..., "error": <problem+json>}`; unknown resources and missing permissions are refused, and one connection joins at most `max_resource_rooms` (default 100) resource rooms. The kernel prefixes every resource room with the organization from the token, so another organization's client never receives it.
4. Handler: in the aggregate's event handler module, `async def push_<aggregate>_changed(event: <EventType>) -> None` calls `push_after_commit(event.name, event.VERSION, data, resources=[("<aggregate>", aggregate_id)])`. `event.aggregate_id` is typed `UUID | None`; an aggregate's own events always carry it, so narrow it first (`aggregate_id = event.aggregate_id`, then raise `ValueError` when it is `None`). Build `data` as a dict literal with camelCase keys, such as `{"id": str(aggregate_id), "<fieldName>": to_json(event.<field_name>, camel_case=True)}` with `to_json` from `fast_ddd.serialization` for each value, because `to_json` of a whole object returns `JsonValue`, not the `Mapping` that `push_after_commit` takes. Hold the id and only fields that the aggregate's response model also exposes; the client fetches anything else over HTTP, where permissions apply. Register it with `bus.subscribe` in `register(bus)`.
5. Rooms: `resources=[...]` reaches clients that joined with the read permission; `users=[user_id]` reaches one user's connections, for example the doer of a long task; `organization=True` reaches every connection of the organization, whatever its permissions, so use it only for data every member may see. A push with no room, or with organization or resource rooms in a unit of work without an organization, raises `RealtimePushError` at the call, inside the transaction; so does `data` that is not JSON.
6. Delivery: the push is sent after the outermost commit and discarded on rollback, like `publish_after_commit`. A failed send is retried once and then only logged. A client receives `{"eventName", "eventVersion", "data"}`. Clients are checked only when they connect and join: a token that expires or loses a permission later does not disconnect them.
7. Contracts: add `socketio` to the `core` contract's `forbidden_modules` in `.importlinter`; only `fast_ddd_adapter.realtime` and `fast_ddd_port.realtime` touch it.
8. Tests: configure a recording emitter in the `infrastructure` fixture, a `RealtimeEmitter` subclass whose `__init__` does not call the parent and whose `emit(event, data, *, to)` appends to a list and `close()` does nothing. Write the stubs for the client calls the tests use (`AsyncClient.__init__`, `connect`, `call`, `on`, `disconnect`), then the tests below, then `make check`.

## Required tests

- Push after commit: an HTTP command that raises the event results in one recorded push with the event name, `eventVersion`, the camelCase `data` and the room `org:<organization>:<aggregate>:<id>`, recorded by the after-commit hook rather than by the handler call.
- Rollback: a command whose transaction rolls back records no push, following `test_rolled_back_void_enqueues_nothing` in `references/example/tests/port/test_invoice_tasks.py`.
- Wiring, with the real endpoint served by uvicorn on `127.0.0.1` with port 0 and the RabbitMQ testcontainer: a client connecting with a token from `TokenFactory` and `auth={"token": ...}` that has `<aggregate>:read` joins the resource room with status `ok` and receives a push sent by the real emitter; a client without the permission gets status `error` with `auth.permission_denied`; a client without a token cannot connect.
- Closing: `Runtime.close()` closes the emitter and the endpoint (`close()` may be called again without error).

## Pitfalls

- Never push from core or from a controller; only adapter event handlers push, so the push follows the commit.
- Never let a client choose its organization or user: rooms come from the token.
- Do not add Redis or a second process; delivery between API instances goes through the existing RabbitMQ.
- Do not re-test the kernel's transport rules (long-polling refusal, connect timeout); its own tests cover them.
