import asyncio
import gc
import json
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import aiohttp
import httpx2
import pytest
import socketio
from socketio.exceptions import ConnectionError as SocketConnectionError
from testcontainers.core.container import DockerContainer

from fast_ddd_adapter.realtime import (
    RealtimeEmitter,
    create_realtime_emitter,
    organization_room,
    resource_room,
    user_room,
)
from fast_ddd_port.auth import JwtVerifier
from fast_ddd_port.realtime import mount_realtime
from fast_ddd_port.testing import TokenFactory
from tests.realtime_support import (
    JWT_SETTINGS,
    PATH,
    SERVICE,
    amqp_tasks,
    connected,
    plain_app,
    running_app,
    settle,
    wait_for_listener,
    wait_until,
)

EVENT = "order.updated"


@pytest.fixture(scope="module")
def tokens() -> TokenFactory:
    return TokenFactory(JWT_SETTINGS)


@pytest.fixture
async def emitter(amqp_url: str) -> AsyncGenerator[RealtimeEmitter]:
    emitter = create_realtime_emitter(amqp_url, service=SERVICE)
    yield emitter
    await emitter.close()


async def refused(url: str, auth: Any, **options: Any) -> dict[str, Any]:
    """Connect expecting the realtime handler's refusal; returns its problem+json."""
    errors = await refused_errors(url, auth, **options)
    assert errors[0]["message"] == errors[0]["data"]["code"]
    return errors[0]["data"]


async def refused_errors(url: str, auth: Any, **options: Any) -> list[Any]:
    """Connect expecting a refusal; returns what connect_error delivered (if anything)."""
    http = aiohttp.ClientSession()
    sio = socketio.AsyncClient(reconnection=False, http_session=http)
    errors: list[Any] = []
    received: list[str] = []

    async def on_error(data: Any) -> None:
        errors.append(data)

    async def on_any(event: str, *_: Any) -> None:
        received.append(event)

    sio.on("connect_error", on_error)
    sio.on("*", on_any)
    try:
        with pytest.raises(SocketConnectionError):
            await sio.connect(
                url,
                auth=auth,
                transports=options.pop("transports", ["websocket"]),
                socketio_path=f"{PATH.lstrip('/')}/socket.io",
                **options,
            )
    finally:
        await http.close()
    assert not sio.connected
    assert received == []
    return errors


async def test_mounted_endpoint_accepts_websocket_and_keeps_http_routes(
    tokens: TokenFactory, amqp_url: str
) -> None:
    async with running_app(tokens, amqp_url) as running:
        async with connected(running.url, {"token": tokens.token(organization_id=None)}) as c:
            assert c.sio.connected
        async with httpx2.AsyncClient(base_url=running.url) as http:
            assert (await http.get("/ping")).json() == {"status": "ok"}
            assert (await http.get("/socket.io/")).status_code == 404


@pytest.mark.parametrize(
    ("auth", "code"),
    [
        (None, "auth.unauthenticated"),
        ({}, "auth.unauthenticated"),
        ({"token": 123}, "auth.unauthenticated"),
        ({"token": {"value": "x"}}, "auth.unauthenticated"),
        ({"token": "not-a-jwt"}, "auth.token_invalid"),
    ],
)
async def test_connection_without_a_valid_token_is_refused(
    tokens: TokenFactory, amqp_url: str, auth: Any, code: str
) -> None:
    async with running_app(tokens, amqp_url) as running:
        problem = await refused(running.url, auth)
    assert problem["code"] == code
    assert problem["status"] == 401


async def test_foreign_signature_and_expired_token_are_refused(
    tokens: TokenFactory, amqp_url: str
) -> None:
    foreign = TokenFactory(JWT_SETTINGS).token(organization_id=uuid4())
    expired = tokens.token(organization_id=uuid4(), expires_in=-60)
    async with running_app(tokens, amqp_url) as running:
        assert (await refused(running.url, {"token": foreign}))["code"] == "auth.token_invalid"
        assert (await refused(running.url, {"token": expired}))["code"] == "auth.token_expired"


async def test_unreachable_jwks_refuses_with_service_unavailable(
    tokens: TokenFactory, amqp_url: str
) -> None:
    failing = JwtVerifier(
        JWT_SETTINGS,
        httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: httpx2.Response(500))),
    )
    async with running_app(tokens, amqp_url, verifier=failing) as running:
        problem = await refused(running.url, {"token": tokens.token(organization_id=uuid4())})
    assert problem["code"] == "server.unavailable"


async def test_connection_joins_its_own_organization_and_user_rooms(
    tokens: TokenFactory, amqp_url: str, emitter: RealtimeEmitter
) -> None:
    organization_id = uuid4()
    async with running_app(tokens, amqp_url) as running:
        token = tokens.token(organization_id=organization_id, user_id="alice")
        async with connected(running.url, {"token": token}, events=[EVENT]) as client:
            await wait_for_listener(emitter, client, "alice")
            await emitter.emit(EVENT, {"to": "org"}, to=[organization_room(organization_id)])
            await emitter.emit(EVENT, {"to": "user"}, to=[user_room("alice")])
            await wait_until(lambda: len(client.events(EVENT)) == 2)
    assert sorted(e["to"] for e in client.events(EVENT)) == ["org", "user"]


async def test_organization_and_user_supplied_by_the_client_are_ignored(
    tokens: TokenFactory, amqp_url: str, emitter: RealtimeEmitter
) -> None:
    own, other = uuid4(), uuid4()
    order_id = uuid4()
    async with running_app(tokens, amqp_url) as running:
        token = tokens.token(organization_id=own, user_id="alice", permissions=["order:read"])
        auth = {"token": token, "organizationId": str(other), "userId": "mallory"}
        query = f"?organizationId={other}&userId=mallory"
        async with connected(running.url, auth, events=[EVENT], query=query) as client:
            await wait_for_listener(emitter, client, "alice")
            ack = await client.sio.call(
                "join", {"resource": "order", "id": str(order_id), "organizationId": str(other)}
            )
            assert ack["status"] == "ok"
            for room in (
                organization_room(other),
                user_room("mallory"),
                resource_room(other, "order", order_id),
            ):
                await emitter.emit(EVENT, {"room": room}, to=[room])
            await settle()
            assert client.events(EVENT) == []
            own_room = resource_room(own, "order", order_id)
            await emitter.emit(EVENT, {"room": own_room}, to=[own_room])
            await wait_until(lambda: client.events(EVENT) == [{"room": own_room}])


async def test_token_without_organization_joins_only_the_user_room(
    tokens: TokenFactory, amqp_url: str, emitter: RealtimeEmitter
) -> None:
    async with running_app(tokens, amqp_url) as running:
        token = tokens.token(organization_id=None, user_id="bob", permissions=["order:read"])
        async with connected(running.url, {"token": token}, events=[EVENT]) as client:
            await wait_for_listener(emitter, client, "bob")
            await emitter.emit(EVENT, {"to": "user"}, to=[user_room("bob")])
            await wait_until(lambda: client.events(EVENT) == [{"to": "user"}])
            ack = await client.join("order", uuid4())
    assert ack["status"] == "error"
    assert ack["error"]["code"] == "auth.permission_denied"
    assert ack["error"]["detail"] == "the token has no organization"


async def test_only_websocket_transport_is_served(tokens: TokenFactory, amqp_url: str) -> None:
    async with running_app(tokens, amqp_url) as running:
        async with httpx2.AsyncClient(base_url=running.url) as http:
            response = await http.get(
                f"{PATH}/socket.io/", params={"EIO": "4", "transport": "polling"}
            )
        assert response.status_code == 400
        await refused_errors(
            running.url,
            {"token": tokens.token(organization_id=uuid4())},
            transports=["polling"],
        )


@pytest.mark.parametrize(
    ("allowed", "origin", "accepted"),
    [
        (None, "same", True),
        (None, "https://evil.example", False),
        (["https://frontend.test"], "https://frontend.test", True),
        (["https://frontend.test"], "https://evil.example", False),
    ],
)
async def test_origin_is_checked(
    tokens: TokenFactory, amqp_url: str, allowed: list[str] | None, origin: str, accepted: bool
) -> None:
    async with running_app(tokens, amqp_url, cors_allowed_origins=allowed) as running:
        headers = {"Origin": running.url if origin == "same" else origin}
        auth = {"token": tokens.token(organization_id=uuid4())}
        if accepted:
            async with connected(running.url, auth, headers=headers) as client:
                assert client.sio.connected
        else:
            await refused_errors(running.url, auth, headers=headers)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"cors_allowed_origins": []}, "cors_allowed_origins"),
        ({"path": "realtime"}, "path"),
        ({"path": "/realtime/"}, "path"),
        ({"resources": {"Order": "order:read"}}, "snake_case"),
        ({"resources": {"order": "order read"}}, "single token"),
        ({"resources": {"order": ""}}, "single token"),
        ({"max_resource_rooms": 0}, "max_resource_rooms"),
        ({"cors_allowed_origins": "https://frontend.test"}, "not one string"),
        ({"connect_timeout_seconds": 0}, "connect_timeout_seconds"),
        ({"service": "Billing"}, "service name"),
    ],
)
def test_mount_rejects_unsafe_configuration(
    tokens: TokenFactory, options: dict[str, Any], message: str
) -> None:
    arguments: dict[str, Any] = {
        "verifier": tokens.verifier(),
        "resources": {"order": "order:read"},
        "rabbitmq_url": "amqp://unused/",
        "service": SERVICE,
        **options,
    }
    with pytest.raises(ValueError, match=message):
        mount_realtime(plain_app(), **arguments)


@pytest.mark.parametrize(
    ("permissions", "payload", "code"),
    [
        ([], {"resource": "order", "id": "ID"}, "auth.permission_denied"),
        (["order:read"], {"resource": "invoice", "id": "ID"}, "auth.permission_denied"),
        (["order:read"], {"resource": "order", "id": "not-a-uuid"}, "validation.failed"),
        (["order:read"], {"resource": "order"}, "validation.failed"),
        (["order:read"], "order", "validation.failed"),
    ],
)
async def test_resource_room_join_is_refused_with_a_problem(
    tokens: TokenFactory,
    amqp_url: str,
    emitter: RealtimeEmitter,
    permissions: list[str],
    payload: Any,
    code: str,
) -> None:
    organization_id, order_id = uuid4(), uuid4()
    if payload == {"resource": "order", "id": "ID"} or payload == {
        "resource": "invoice",
        "id": "ID",
    }:
        payload = {"resource": payload["resource"], "id": str(order_id)}
    async with running_app(tokens, amqp_url) as running:
        token = tokens.token(
            organization_id=organization_id, user_id="carol", permissions=permissions
        )
        async with connected(running.url, {"token": token}, events=[EVENT]) as client:
            await wait_for_listener(emitter, client, "carol")
            ack = await client.sio.call("join", payload)
            room = resource_room(organization_id, "order", order_id)
            await emitter.emit(EVENT, {}, to=[room])
            await settle()
            assert client.events(EVENT) == []
    assert ack["status"] == "error"
    assert ack["data"] is None
    assert ack["error"]["code"] == code
    assert {"type", "title", "status"} <= ack["error"].keys()


async def test_permitted_client_joins_the_resource_room_and_receives_its_pushes(
    tokens: TokenFactory, amqp_url: str, emitter: RealtimeEmitter
) -> None:
    organization_id, order_id = uuid4(), uuid4()
    async with running_app(tokens, amqp_url) as running:
        token = tokens.token(
            organization_id=organization_id, user_id="dave", permissions=["order:read"]
        )
        async with connected(running.url, {"token": token}, events=[EVENT]) as client:
            await wait_for_listener(emitter, client, "dave")
            ack = await client.join("order", order_id)
            room = resource_room(organization_id, "order", order_id)
            await emitter.emit(EVENT, {"id": str(order_id)}, to=[room])
            await wait_until(lambda: client.events(EVENT) == [{"id": str(order_id)}])
    assert ack == {"status": "ok", "data": None, "error": None}


async def test_same_resource_id_in_another_organization_stays_isolated(
    tokens: TokenFactory, amqp_url: str, emitter: RealtimeEmitter
) -> None:
    org_a, org_b, order_id = uuid4(), uuid4(), uuid4()
    async with running_app(tokens, amqp_url) as running:
        token_a = tokens.token(organization_id=org_a, user_id="a", permissions=["order:read"])
        token_b = tokens.token(organization_id=org_b, user_id="b", permissions=["order:read"])
        async with (
            connected(running.url, {"token": token_a}, events=[EVENT]) as client_a,
            connected(running.url, {"token": token_b}, events=[EVENT]) as client_b,
        ):
            await wait_for_listener(emitter, client_a, "a")
            await wait_for_listener(emitter, client_b, "b")
            assert (await client_a.join("order", order_id))["status"] == "ok"
            assert (await client_b.join("order", order_id))["status"] == "ok"
            await emitter.emit(EVENT, {"org": "a"}, to=[resource_room(org_a, "order", order_id)])
            await wait_until(lambda: client_a.events(EVENT) == [{"org": "a"}])
            await settle()
            assert client_b.events(EVENT) == []


async def test_left_resource_room_receives_no_more_pushes(
    tokens: TokenFactory, amqp_url: str, emitter: RealtimeEmitter
) -> None:
    organization_id, order_id = uuid4(), uuid4()
    room = resource_room(organization_id, "order", order_id)
    async with running_app(tokens, amqp_url) as running:
        token = tokens.token(
            organization_id=organization_id, user_id="erin", permissions=["order:read"]
        )
        async with connected(running.url, {"token": token}, events=[EVENT]) as client:
            await wait_for_listener(emitter, client, "erin")
            await client.join("order", order_id)
            await emitter.emit(EVENT, {"n": 1}, to=[room])
            await wait_until(lambda: client.events(EVENT) == [{"n": 1}])
            assert await client.leave("order", order_id) == {
                "status": "ok",
                "data": None,
                "error": None,
            }
            await emitter.emit(EVENT, {"n": 2}, to=[room])
            await settle()
            assert client.events(EVENT) == [{"n": 1}]
            assert (await client.leave("order", "bad"))["error"]["code"] == "validation.failed"


async def test_push_from_one_instance_reaches_clients_of_another(
    tokens: TokenFactory, amqp_url: str, emitter: RealtimeEmitter
) -> None:
    organization_id = uuid4()
    async with (
        running_app(tokens, amqp_url) as instance_a,
        running_app(tokens, amqp_url) as instance_b,
    ):
        token = tokens.token(organization_id=organization_id, user_id="frank")
        async with (
            connected(instance_a.url, {"token": tokens.token(organization_id=None)}),
            connected(instance_b.url, {"token": token}, events=[EVENT]) as client,
        ):
            await wait_for_listener(emitter, client, "frank")
            await instance_a.realtime.server.emit(
                EVENT, {"from": "a"}, to=organization_room(organization_id)
            )
            await wait_until(lambda: client.events(EVENT) == [{"from": "a"}])


async def test_delivery_resumes_after_the_broker_drops_connections(
    tokens: TokenFactory, amqp_url: str, rabbitmq: DockerContainer, emitter: RealtimeEmitter
) -> None:
    async with running_app(tokens, amqp_url) as running:
        token = tokens.token(organization_id=None, user_id="grace")
        async with connected(running.url, {"token": token}) as client:
            await wait_for_listener(emitter, client, "grace")
            result = await asyncio.to_thread(
                rabbitmq.exec, ["rabbitmqctl", "close_all_connections", "kernel test"]
            )
            assert result.exit_code == 0
            await wait_for_listener(emitter, client, "grace")


@pytest.mark.parametrize("timing", ["never_connected", "first_connection", "listener_ready"])
async def test_server_close_leaves_no_amqp_tasks(
    tokens: TokenFactory, amqp_url: str, timing: str
) -> None:
    before = set(amqp_tasks())
    emitter = create_realtime_emitter(amqp_url, service=SERVICE)
    try:
        async with running_app(tokens, amqp_url) as running:
            if timing != "never_connected":
                token = tokens.token(organization_id=None, user_id="heidi")
                async with connected(running.url, {"token": token}) as client:
                    if timing == "listener_ready":
                        await wait_for_listener(emitter, client, "heidi")
    finally:
        await emitter.close()
    await asyncio.sleep(0.1)
    gc.collect()
    assert set(amqp_tasks()) - before == set()


async def test_refused_connection_is_closed_on_the_server(
    tokens: TokenFactory, amqp_url: str
) -> None:
    """A client ignoring connect_error loses its Engine.IO session; the server stops pinging it,
    so the transport closes within ping_interval + ping_timeout instead of staying alive."""
    async with running_app(tokens, amqp_url) as running:
        url = running.url.replace("http", "ws") + f"{PATH}/socket.io/?EIO=4&transport=websocket"
        async with aiohttp.ClientSession() as http, http.ws_connect(url) as ws:
            assert (await ws.receive_str(timeout=5)).startswith("0")
            await ws.send_str('40{"token":"not-a-jwt"}')
            assert (await ws.receive_str(timeout=5)).startswith("44")
            assert await ws.receive_str(timeout=5) == "1"
            assert running.realtime.server.eio.sockets == {}


async def test_resource_rooms_per_connection_are_bounded(
    tokens: TokenFactory, amqp_url: str
) -> None:
    organization_id = uuid4()
    first, second, third = uuid4(), uuid4(), uuid4()
    async with running_app(tokens, amqp_url, max_resource_rooms=2) as running:
        token = tokens.token(organization_id=organization_id, permissions=["order:read"])
        async with connected(running.url, {"token": token}) as client:
            assert (await client.join("order", first))["status"] == "ok"
            assert (await client.join("order", second))["status"] == "ok"
            assert (await client.join("order", first))["status"] == "ok"
            refusal = await client.join("order", third)
            assert refusal["status"] == "error"
            assert refusal["error"]["code"] == "rate_limit.exceeded"
            assert (await client.leave("order", first))["status"] == "ok"
            assert (await client.join("order", third))["status"] == "ok"


@pytest.mark.parametrize("leaves_namespace", [False, True])
async def test_transport_without_a_connection_is_closed_after_the_connect_timeout(
    tokens: TokenFactory, amqp_url: str, leaves_namespace: bool
) -> None:
    async with running_app(tokens, amqp_url, connect_timeout_seconds=0.5) as running:
        url = running.url.replace("http", "ws") + f"{PATH}/socket.io/?EIO=4&transport=websocket"
        async with aiohttp.ClientSession() as http, http.ws_connect(url) as ws:
            assert (await ws.receive_str(timeout=5)).startswith("0")
            if leaves_namespace:
                token = tokens.token(organization_id=None)
                await ws.send_str("40" + json.dumps({"token": token}))
                assert (await ws.receive_str(timeout=5)).startswith("40")
                await ws.send_str("41")
            assert await ws.receive_str(timeout=5) == "1"
            assert running.realtime.server.eio.sockets == {}


async def test_authenticated_connection_outlives_the_connect_timeout(
    tokens: TokenFactory, amqp_url: str
) -> None:
    async with running_app(tokens, amqp_url, connect_timeout_seconds=0.3) as running:
        token = tokens.token(organization_id=None)
        async with connected(running.url, {"token": token}) as client:
            await asyncio.sleep(1)
            assert client.sio.connected
            assert len(running.realtime.server.eio.sockets) == 1


async def test_connection_after_close_is_rejected_without_restarting_the_listener(
    tokens: TokenFactory, amqp_url: str
) -> None:
    before = amqp_tasks()
    async with running_app(tokens, amqp_url) as running:
        await running.realtime.close()
        await refused_errors(running.url, {"token": tokens.token(organization_id=None)})
        await asyncio.sleep(0.2)
        assert amqp_tasks() - before == set()
        assert running.realtime.server.eio.sockets == {}


async def test_close_shuts_the_listener_connection_while_a_message_is_handled(
    tokens: TokenFactory,
    amqp_url: str,
    emitter: RealtimeEmitter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running_app(tokens, amqp_url) as running:
        token = tokens.token(organization_id=None, user_id="judy")
        async with connected(running.url, {"token": token}) as client:
            await wait_for_listener(emitter, client, "judy")
            manager = running.realtime.manager
            handling = asyncio.Event()

            async def slow_handle_emit(_: Any) -> None:
                handling.set()
                await asyncio.sleep(5)

            monkeypatch.setattr(manager, "_handle_emit", slow_handle_emit)
            await emitter.emit(EVENT, {}, to=[user_room("judy")])
            await asyncio.wait_for(handling.wait(), 5)
            listener = manager._listener_connection  # pyright: ignore[reportPrivateUsage]
            assert listener is not None
            await running.realtime.close()
            assert listener.is_closed
            await running.realtime.close()


async def test_watchers_end_with_their_transport_and_on_shutdown(
    tokens: TokenFactory, amqp_url: str
) -> None:
    async with running_app(tokens, amqp_url) as running:
        server = running.realtime.server
        watchers: dict[str, asyncio.Task[None]] = getattr(server, "_watchers")  # noqa: B009
        token = tokens.token(organization_id=None)
        async with connected(running.url, {"token": token}):
            await wait_until(lambda: len(watchers) == 1)
            (first,) = watchers.values()
        await wait_until(lambda: not watchers)
        await asyncio.sleep(0)
        assert first.done()
        async with connected(running.url, {"token": token}):
            await wait_until(lambda: len(watchers) == 1)
            (second,) = watchers.values()
            await server.shutdown()
            assert second.done()
