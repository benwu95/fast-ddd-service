import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from opentelemetry.trace import SpanKind
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fast_ddd_adapter.orm import DomainEventModel
from fast_ddd_port.problems import kernel_problem, problem_json, problem_response
from fast_ddd_port.testing import TokenFactory
from tests.port.app_under_test import FRONTEND, JWT_SETTINGS, build_app
from tests.telemetry import Telemetry


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory(JWT_SETTINGS)


@pytest.fixture
async def client(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    tokens: TokenFactory,
) -> AsyncGenerator[httpx2.AsyncClient]:
    app = build_app(engine, session_factory, tokens)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def auth(
    tokens: TokenFactory,
    org: UUID,
    *,
    permissions: str = "order:create order:read order:void",
    expires_in: int = 300,
) -> dict[str, str]:
    return tokens.authorization(
        organization_id=org, permissions=permissions.split(), expires_in=expires_in
    )


async def create_order(
    client: httpx2.AsyncClient, tokens: TokenFactory, org: UUID, **body: Any
) -> httpx2.Response:
    response = await client.post(
        "/orders", json={"code": "c-" + uuid4().hex[:6], **body}, headers=auth(tokens, org)
    )
    assert response.status_code == 201, response.text
    return response


async def test_authentication_failures_are_401_with_challenge(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    missing = await client.get(f"/orders/{uuid4()}")
    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert missing.json()["code"] == "auth.unauthenticated"

    invalid = await client.get(f"/orders/{uuid4()}", headers={"Authorization": "Bearer x.y.z"})
    assert invalid.status_code == 401
    assert invalid.json()["code"] == "auth.token_invalid"
    assert 'error="invalid_token"' in invalid.headers["WWW-Authenticate"]

    expired = await client.get(
        f"/orders/{uuid4()}", headers=auth(tokens, organization_id, expires_in=-120)
    )
    assert expired.json()["code"] == "auth.token_expired"


async def test_missing_permission_is_403(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    response = await client.get(
        f"/orders/{uuid4()}", headers=auth(tokens, organization_id, permissions="order:create")
    )
    assert response.status_code == 403
    assert response.json()["code"] == "auth.permission_denied"


async def test_create_returns_resource_location_and_etag(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    order_id = uuid4()
    response = await create_order(client, tokens, organization_id, id=str(order_id))

    body = response.json()
    assert response.headers["Location"] == f"/orders/{order_id}"
    assert response.headers["ETag"] == '"1"'
    assert body["etag"] == '"1"'
    assert body["createdAt"].endswith("Z")
    assert "created_at" not in body
    assert response.headers["X-Trace-Id"]

    duplicate = await client.post(
        "/orders",
        json={"id": str(order_id), "code": "again"},
        headers=auth(tokens, organization_id),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "kernel_test.order.already_exists"


async def test_not_found_and_route_not_found(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    created = await create_order(client, tokens, organization_id)
    other_org = await client.get(f"/orders/{created.json()['id']}", headers=auth(tokens, uuid4()))
    assert other_org.status_code == 404
    assert other_org.json()["code"] == "kernel_test.order.not_found"

    malformed = await client.get("/orders/not-a-uuid", headers=auth(tokens, organization_id))
    assert malformed.status_code == 404
    assert malformed.json()["code"] == "request.route_not_found"


async def test_preconditions_on_domain_command(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    created = await create_order(client, tokens, organization_id)
    url = f"/orders/{created.json()['id']}/void"
    headers = auth(tokens, organization_id)

    missing = await client.post(url, json={"reason": "r"}, headers=headers)
    assert (missing.status_code, missing.json()["code"]) == (
        428,
        "concurrency.precondition_required",
    )
    star = await client.post(url, json={"reason": "r"}, headers={**headers, "If-Match": "*"})
    assert (star.status_code, star.json()["code"]) == (400, "concurrency.invalid_if_match")
    weak = await client.post(url, json={"reason": "r"}, headers={**headers, "If-Match": 'W/"1"'})
    assert weak.status_code == 400
    stale = await client.post(url, json={"reason": "r"}, headers={**headers, "If-Match": '"9"'})
    assert (stale.status_code, stale.json()["code"]) == (412, "concurrency.etag_mismatch")

    voided = await client.post(url, json={"reason": "r"}, headers={**headers, "If-Match": '"1"'})
    assert voided.status_code == 200
    assert voided.headers["ETag"] == '"2"'

    again = await client.post(url, json={"reason": "r"}, headers={**headers, "If-Match": '"2"'})
    assert again.status_code == 409
    problem = again.json()
    assert problem["code"] == "kernel_test.order.already_voided"
    assert problem["params"] == {"orderId": created.json()["id"]}
    assert problem["title"] == "Order already voided"
    assert again.headers["content-type"] == "application/problem+json"

    unknown = await client.post(
        f"/orders/{uuid4()}/void", json={"reason": "r"}, headers={**headers, "If-Match": '"1"'}
    )
    assert unknown.status_code == 404


async def test_request_shape_errors(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    headers = auth(tokens, organization_id)

    malformed = await client.post(
        "/orders",
        content=b"{not json",
        headers={
            **auth(tokens, organization_id, permissions=""),
            "Content-Type": "application/json",
        },
    )
    assert (malformed.status_code, malformed.json()["code"]) == (400, "request.malformed_json")

    plain = await client.post(
        "/orders", content=b"code=x", headers={**headers, "Content-Type": "text/plain"}
    )
    assert (plain.status_code, plain.json()["code"]) == (415, "request.unsupported_media_type")

    invalid = await client.post(
        "/orders", json={"code": "x" * 60, "created_by": "me"}, headers=headers
    )
    assert invalid.status_code == 422
    errors = {e["code"]: e for e in invalid.json()["errors"]}
    assert errors["validation.string_too_long"]["pointer"] == "#/code"
    assert errors["validation.string_too_long"]["params"] == {"maxLength": 50}
    assert errors["validation.extra_forbidden"]["pointer"] == "#/created_by"


async def test_batch_returns_207_with_per_item_results(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    headers = auth(tokens, organization_id)
    first = (await create_order(client, tokens, organization_id)).json()
    second = (await create_order(client, tokens, organization_id)).json()
    items = [
        {"id": first["id"], "etag": first["etag"], "reason": "r"},
        {"id": second["id"], "etag": '"7"', "reason": "r"},
        {"id": str(uuid4()), "etag": '"1"', "reason": "r"},
    ]

    response = await client.post("/orders/batch-void", json={"items": items}, headers=headers)

    assert response.status_code == 207
    results = response.json()["results"]
    assert [r["status"] for r in results] == [200, 412, 404]
    assert results[0]["data"]["status"] == "voided"
    assert results[1]["error"]["code"] == "concurrency.etag_mismatch"

    duplicated = await client.post(
        "/orders/batch-void", json={"items": [items[0], items[0]]}, headers=headers
    )
    assert duplicated.status_code == 422
    assert duplicated.json()["errors"] == [
        {
            "pointer": "#/items/1/id",
            "code": "validation.duplicate_id",
            "params": {},
            "detail": "The same id appears more than once in this batch",
        }
    ]


async def test_unexpected_error_is_500_with_cors_and_trace_id(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    response = await client.get(
        "/orders/boom", headers={**auth(tokens, organization_id), "Origin": FRONTEND}
    )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert response.json()["traceId"] == response.headers["X-Trace-Id"]
    assert "unexpected" not in response.text


async def test_cors_preflight_allows_write_methods(client: httpx2.AsyncClient) -> None:
    for method in ("POST", "PATCH", "DELETE"):
        response = await client.options(
            "/orders",
            headers={
                "Origin": FRONTEND,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "authorization,content-type,if-match",
            },
        )
        assert response.status_code == 200, method


async def test_openapi_marks_if_match_required_and_uses_readable_operation_ids(
    client: httpx2.AsyncClient,
) -> None:
    schema = (await client.get("/openapi.json")).json()
    void = schema["paths"]["/orders/{order_id}/void"]["post"]

    assert void["operationId"] == "voidOrder"
    if_match = next(p for p in void["parameters"] if p["name"] == "If-Match")
    assert if_match["required"] is True


async def test_health_endpoints_are_public(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/health/ready")).json() == {"status": "ok"}


async def event_context(
    factory: async_sessionmaker[AsyncSession],
) -> dict[UUID | None, tuple[UUID | None, str | None]]:
    async with factory() as session:
        rows = await session.execute(
            select(
                DomainEventModel.aggregate_id,
                DomainEventModel.organization_id,
                DomainEventModel.trace_id,
            )
        )
        return {row[0]: (row[1], row[2]) for row in rows}


async def test_trace_id_is_the_server_spans_and_is_recorded_on_events(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
    session_factory: async_sessionmaker[AsyncSession],
    telemetry: Telemetry,
) -> None:
    response = await create_order(client, tokens, organization_id)
    trace_id = response.headers["X-Trace-Id"]

    assert [span.kind for span in telemetry.spans(trace_id)].count(SpanKind.SERVER) == 1
    assert await event_context(session_factory) == {
        UUID(response.json()["id"]): (organization_id, trace_id)
    }

    order_path = response.headers["Location"]
    await client.get(order_path, headers=auth(tokens, organization_id))
    routes = {
        (attributes["http.method"], attributes.get("http.target"))
        for attributes, _ in telemetry.points("http.server.duration")
    }
    assert {("POST", "/orders"), ("GET", "/orders/{order_id}")} <= routes
    assert order_path not in {target for _, target in routes}


async def test_concurrent_requests_keep_their_own_context(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organizations = [uuid4(), uuid4()]
    responses = await asyncio.gather(
        *(create_order(client, tokens, organizations[i % 2]) for i in range(10))
    )

    expected = {
        UUID(response.json()["id"]): (organizations[i % 2], response.headers["X-Trace-Id"])
        for i, response in enumerate(responses)
    }
    assert await event_context(session_factory) == expected
    assert len({trace_id for _, trace_id in expected.values()}) == 10


def test_problem_json_is_the_problem_response_body() -> None:
    problem = kernel_problem("auth.permission_denied", "missing permission invoice:void")
    body = problem_json(problem)
    assert body == {
        "type": "/problems/auth.permission_denied",
        "title": "Permission denied",
        "status": 403,
        "detail": "missing permission invoice:void",
        "code": "auth.permission_denied",
        "params": {},
    }
    assert problem_response(problem).body == problem_response(problem).render(body)
