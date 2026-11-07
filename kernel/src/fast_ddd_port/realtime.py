"""Socket.IO endpoint for realtime push: JWT on connect, permission-checked resource rooms.

Needs the ``realtime`` extra. The organization and user always come from the token; clients
can only join resource rooms inside their own organization.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

try:
    import socketio
    from socketio.exceptions import ConnectionRefusedError as SocketConnectionRefusedError
except ImportError as error:
    raise ImportError(
        "realtime push needs the socketio dependency: install fast-ddd-kernel[realtime]"
    ) from error

from fastapi import FastAPI

from fast_ddd_adapter.realtime import (
    KernelAioPikaManager,
    is_resource_name,
    organization_room,
    realtime_channel,
    resource_room,
    user_room,
)
from fast_ddd_port.auth import JwtVerifier, Principal, ensure_permission
from fast_ddd_port.problems import HttpProblem, kernel_problem, problem_json

logger = logging.getLogger(__name__)

_CONNECTION = "fast_ddd_connection"


def _refused(code: str, detail: str | None = None) -> SocketConnectionRefusedError:
    # The client's connect_error carries {"message": code, "data": problem+json}.
    return SocketConnectionRefusedError(code, problem_json(kernel_problem(code, detail)))


def _ok() -> dict[str, Any]:
    return {"status": "ok", "data": None, "error": None}


def _error(problem: HttpProblem) -> dict[str, Any]:
    error = problem_json(kernel_problem(problem.code, problem.detail))
    return {"status": "error", "data": None, "error": error}


@dataclass(slots=True)
class _Connection:
    principal: Principal
    resource_rooms: set[str] = field(default_factory=set[str])


class _KernelSocketServer(socketio.AsyncServer):
    """Ends Engine.IO sessions that hold no authenticated Socket.IO connection.

    python-socketio keeps a refused session alive and has no connect timeout, so a client that
    answers pings could hold a transport without ever authenticating. A refused connection is
    closed at once; one without a connection is closed after ``connect_timeout_seconds``.
    Without a session the server stops pinging, and engineio drops the WebSocket within
    ping_interval + ping_timeout even if the client keeps it open.
    """

    def __init__(self, *, connect_timeout_seconds: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._connect_timeout = connect_timeout_seconds
        self._watchers: dict[str, asyncio.Task[None]] = {}
        self._shut_down = False

    def _connected(self, eio_sid: str) -> bool:
        return self.manager.sid_from_eio_sid(eio_sid, "/") is not None

    async def _handle_eio_connect(self, eio_sid: str, environ: Any) -> bool | None:
        if self._shut_down:
            return False  # engineio rejects the transport; nothing reaches the manager
        await super()._handle_eio_connect(eio_sid, environ)
        self._watchers[eio_sid] = asyncio.create_task(self._close_when_unconnected(eio_sid))
        return None

    async def _handle_eio_disconnect(self, eio_sid: str, reason: Any) -> None:
        await super()._handle_eio_disconnect(eio_sid, reason)
        watcher = self._watchers.pop(eio_sid, None)
        if watcher is not None and watcher is not asyncio.current_task():
            watcher.cancel()

    async def _handle_connect(self, eio_sid: str, namespace: str | None, data: Any) -> None:
        await super()._handle_connect(eio_sid, namespace, data)
        if not self._connected(eio_sid):
            await self.eio.disconnect(eio_sid)

    async def _close_when_unconnected(self, eio_sid: str) -> None:
        # Re-checked every period: a client may also leave the namespace and keep the transport.
        while True:
            await asyncio.sleep(self._connect_timeout)
            if not self._connected(eio_sid):
                await self.eio.disconnect(eio_sid)
                return

    async def shutdown(self) -> None:
        if self._shut_down:  # engineio's shutdown fails when called a second time
            return
        self._shut_down = True
        watchers = list(self._watchers.values())
        self._watchers.clear()
        for watcher in watchers:
            watcher.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
        await super().shutdown()


class _Handlers:
    def __init__(
        self,
        server: socketio.AsyncServer,
        verifier: JwtVerifier,
        resources: Mapping[str, str],
        max_resource_rooms: int,
    ) -> None:
        self._server = server
        self._verifier = verifier
        self._resources = dict(resources)
        self._max_resource_rooms = max_resource_rooms

    async def connect(self, sid: str, _environ: Mapping[str, Any], auth: object = None) -> None:
        token = cast(dict[str, object], auth).get("token") if isinstance(auth, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise _refused("auth.unauthenticated")
        try:
            principal = await self._verifier.verify(token)
        except HttpProblem as problem:
            raise _refused(problem.code, problem.detail) from None
        except Exception:
            logger.exception("realtime token verification failed")
            raise _refused("server.unavailable") from None
        await self._server.save_session(sid, {_CONNECTION: _Connection(principal)})
        await self._server.enter_room(sid, user_room(principal.user.id))
        if principal.organization_id is not None:
            await self._server.enter_room(sid, organization_room(principal.organization_id))

    async def join(self, sid: str, payload: object = None) -> dict[str, Any]:
        connection = await self._connection(sid)
        try:
            resource, room = self._room(connection.principal, payload)
            ensure_permission(connection.principal, self._resources[resource])
            rooms = connection.resource_rooms
            if room not in rooms and len(rooms) >= self._max_resource_rooms:
                raise HttpProblem(
                    "rate_limit.exceeded",
                    detail=f"at most {self._max_resource_rooms} resource rooms per connection",
                )
        except HttpProblem as problem:
            return _error(problem)
        connection.resource_rooms.add(room)
        await self._server.save_session(sid, {_CONNECTION: connection})
        await self._server.enter_room(sid, room)
        return _ok()

    async def leave(self, sid: str, payload: object = None) -> dict[str, Any]:
        connection = await self._connection(sid)
        try:
            _, room = self._room(connection.principal, payload)
        except HttpProblem as problem:
            return _error(problem)
        connection.resource_rooms.discard(room)
        await self._server.save_session(sid, {_CONNECTION: connection})
        await self._server.leave_room(sid, room)
        return _ok()

    async def _connection(self, sid: str) -> _Connection:
        return cast(_Connection, (await self._server.get_session(sid))[_CONNECTION])

    def _room(self, principal: Principal, payload: object) -> tuple[str, str]:
        fields = cast(dict[str, object], payload) if isinstance(payload, dict) else {}
        resource, raw_id = fields.get("resource"), fields.get("id")
        if not isinstance(resource, str) or not isinstance(raw_id, str):
            raise HttpProblem("validation.failed", detail="expected {resource: str, id: str}")
        try:
            resource_id = UUID(raw_id)
        except ValueError:
            raise HttpProblem("validation.failed", detail="id must be a UUID") from None
        if resource not in self._resources:
            raise HttpProblem("auth.permission_denied", detail=f"unknown resource {resource}")
        if principal.organization_id is None:
            raise HttpProblem("auth.permission_denied", detail="the token has no organization")
        return resource, resource_room(principal.organization_id, resource, resource_id)


@dataclass(frozen=True, slots=True)
class RealtimeServer:
    server: socketio.AsyncServer
    manager: KernelAioPikaManager

    async def close(self) -> None:
        """Stop the Socket.IO server and its RabbitMQ listener; call it on app shutdown."""
        await self.server.shutdown()
        await self.manager.close()


def mount_realtime(
    app: FastAPI,
    *,
    verifier: JwtVerifier,
    resources: Mapping[str, str],
    rabbitmq_url: str,
    service: str,
    cors_allowed_origins: Sequence[str] | None = None,
    path: str = "/realtime",
    max_resource_rooms: int = 100,
    connect_timeout_seconds: float = 45.0,
) -> RealtimeServer:
    """Mount a WebSocket-only Socket.IO endpoint at ``{path}/socket.io``.

    ``resources`` maps each joinable resource name (lower snake_case) to the permission that
    ``require()`` would check over HTTP. ``cors_allowed_origins=None`` allows the same origin
    only; engineio derives the scheme from ``X-Forwarded-Proto`` (else http), so behind TLS the
    proxy must send that header, and a frontend on another origin needs an explicit list.
    ``max_resource_rooms`` bounds the resource rooms one connection may join, and a transport
    that has not completed an authenticated connection is closed after
    ``connect_timeout_seconds`` (Socket.IO's own server default is 45 seconds). ``service``
    scopes the RabbitMQ fanout exchange; use the same name for ``create_realtime_emitter``.
    """
    if not path.startswith("/") or path.endswith("/"):
        raise ValueError(f"path must start with '/' and not end with it: {path!r}")
    for name, permission in resources.items():
        if not is_resource_name(name):
            raise ValueError(f"resource name must be lower snake_case: {name!r}")
        if not permission or permission != permission.strip() or " " in permission:
            raise ValueError(f"permission for {name!r} must be a single token: {permission!r}")
    if max_resource_rooms < 1:
        raise ValueError("max_resource_rooms must be at least 1")
    if connect_timeout_seconds <= 0:
        raise ValueError("connect_timeout_seconds must be positive")
    if isinstance(cors_allowed_origins, str):
        raise ValueError("cors_allowed_origins must be a sequence of origins, not one string")
    if cors_allowed_origins is not None and not cors_allowed_origins:
        raise ValueError("cors_allowed_origins must be None (same origin) or non-empty")
    manager = KernelAioPikaManager(rabbitmq_url, channel=realtime_channel(service))
    server = _KernelSocketServer(
        connect_timeout_seconds=connect_timeout_seconds,
        client_manager=manager,
        async_mode="asgi",
        transports=["websocket"],
        cors_allowed_origins=(None if cors_allowed_origins is None else list(cors_allowed_origins)),
    )
    handlers = _Handlers(server, verifier, resources, max_resource_rooms)
    server.on("connect", handlers.connect)
    server.on("join", handlers.join)
    server.on("leave", handlers.leave)
    app.mount(path, socketio.ASGIApp(server, socketio_path=f"{path.lstrip('/')}/socket.io"))
    return RealtimeServer(server=server, manager=manager)
