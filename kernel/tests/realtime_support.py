"""Run a FastAPI app with the realtime endpoint under uvicorn and talk to it with real clients."""

import asyncio
import time
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import aiohttp
import socketio
import uvicorn
from fastapi import FastAPI

from fast_ddd_adapter.realtime import RealtimeEmitter, realtime_channel, user_room
from fast_ddd_port.auth import JwtVerifier
from fast_ddd_port.realtime import RealtimeServer, mount_realtime
from fast_ddd_port.settings import JwtSettings
from fast_ddd_port.testing import TokenFactory

JWT_SETTINGS = JwtSettings(
    issuer="https://issuer.test",
    audience="kernel-realtime-tests",
    jwks_url="https://issuer.test/jwks",
    user_id_claim="sub",
    organization_id_claim="org",
    permissions_claim="scope",
    permissions_format="space_separated",
)
RESOURCES = {"order": "order:read"}
SERVICE = "kernel-tests"
CHANNEL = realtime_channel(SERVICE)
PATH = "/realtime"
PROBE = "kernel.probe"


@dataclass
class RunningApp:
    url: str
    realtime: RealtimeServer
    app: FastAPI


def plain_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    return app


@asynccontextmanager
async def running_app(
    tokens: TokenFactory,
    amqp_url: str,
    *,
    app: FastAPI | None = None,
    resources: Mapping[str, str] = RESOURCES,
    cors_allowed_origins: Sequence[str] | None = None,
    verifier: JwtVerifier | None = None,
    max_resource_rooms: int = 100,
    service: str = SERVICE,
    connect_timeout_seconds: float = 45.0,
) -> AsyncGenerator[RunningApp]:
    app = app or plain_app()
    realtime = mount_realtime(
        app,
        verifier=verifier or tokens.verifier(),
        resources=resources,
        rabbitmq_url=amqp_url,
        service=service,
        connect_timeout_seconds=connect_timeout_seconds,
        cors_allowed_origins=cors_allowed_origins,
        path=PATH,
        max_resource_rooms=max_resource_rooms,
    )
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, lifespan="off", ws="wsproto", log_level="warning"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        await wait_until(lambda: server.started)
        port: int = server.servers[0].sockets[0].getsockname()[1]
        yield RunningApp(url=f"http://127.0.0.1:{port}", realtime=realtime, app=app)
    finally:
        try:
            await realtime.close()
        finally:
            server.should_exit = True
            await task


@dataclass
class Client:
    sio: socketio.AsyncClient
    received: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])

    def events(self, name: str) -> list[Any]:
        return [data for event, data in self.received if event == name]

    async def join(self, resource: str, resource_id: UUID | str) -> dict[str, Any]:
        return await self.sio.call("join", {"resource": resource, "id": str(resource_id)})

    async def leave(self, resource: str, resource_id: UUID | str) -> dict[str, Any]:
        return await self.sio.call("leave", {"resource": resource, "id": str(resource_id)})


@asynccontextmanager
async def connected(
    url: str,
    auth: Any,
    *,
    events: Sequence[str] = (),
    headers: Mapping[str, str] | None = None,
    query: str = "",
) -> AsyncGenerator[Client]:
    http = aiohttp.ClientSession()
    sio = socketio.AsyncClient(reconnection=False, http_session=http)
    client = Client(sio)
    for name in (PROBE, *events):

        async def record(data: Any, name: str = name) -> None:
            client.received.append((name, data))

        sio.on(name, record)
    try:
        await sio.connect(
            url + query,
            auth=auth,
            headers=dict(headers or {}),
            transports=["websocket"],
            socketio_path=f"{PATH.lstrip('/')}/socket.io",
        )
        yield client
    finally:
        await sio.disconnect()
        await http.close()


async def wait_until(predicate: Callable[[], bool], within: float = 10.0) -> None:
    deadline = time.monotonic() + within
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.02)


async def wait_for_listener(emitter: RealtimeEmitter, client: Client, user_id: str) -> None:
    """Push probes until one arrives: a server's queue is bound only after its first connection."""
    deadline = time.monotonic() + 15
    while not client.events(PROBE):
        if time.monotonic() > deadline:
            raise TimeoutError("realtime listener never became ready")
        await emitter.emit(PROBE, {}, to=[user_room(user_id)])
        await asyncio.sleep(0.1)
    client.received.clear()


async def settle() -> None:
    """Give a push that should not arrive the time a delivered one would have taken."""
    await asyncio.sleep(0.5)


def amqp_tasks() -> set[asyncio.Task[Any]]:
    """Tasks running aiormq/aio-pika code; a clean close leaves none behind."""

    def from_amqp(task: asyncio.Task[Any]) -> bool:
        code = getattr(task.get_coro(), "cr_code", None)
        filename: str = getattr(code, "co_filename", "")
        return any(f"/{package}/" in filename for package in ("aiormq", "aio_pika"))

    return {task for task in asyncio.all_tasks() if from_amqp(task)}
