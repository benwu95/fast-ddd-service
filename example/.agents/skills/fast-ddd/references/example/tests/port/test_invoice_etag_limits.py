import sys
from collections.abc import Iterator
from uuid import UUID, uuid4

import httpx2
import pytest
from fast_ddd_port.problems import Problem
from fast_ddd_port.testing import TokenFactory

from tests.port.test_invoice_api import auth, create


@pytest.fixture
def oversized_etag() -> Iterator[str]:
    original = sys.get_int_max_str_digits()
    limit = sys.int_info.default_max_str_digits
    sys.set_int_max_str_digits(limit)
    try:
        yield '"' + "9" * (limit + 1) + '"'
    finally:
        sys.set_int_max_str_digits(original)


@pytest.mark.parametrize("method", ["PATCH", "DELETE", "POST"])
@pytest.mark.parametrize("exists", [False, True])
async def test_oversized_if_match_is_400_before_resource_lookup(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
    oversized_etag: str,
    method: str,
    exists: bool,
) -> None:
    invoice = await create(client, tokens, organization_id) if exists else None
    invoice_id = invoice["id"] if invoice else str(uuid4())
    path = f"/invoices/{invoice_id}" + ("/void" if method == "POST" else "")

    response = await client.request(
        method,
        path,
        json={"reason": "r"} if method == "POST" else {},
        headers={**auth(tokens, organization_id), "If-Match": oversized_etag},
    )

    problem = Problem.model_validate(response.json())
    assert (response.status_code, problem.code) == (400, "concurrency.invalid_if_match")
    assert response.headers["content-type"] == "application/problem+json"
    assert problem.trace_id == response.headers["X-Trace-Id"]
    if invoice:
        current = await client.get(f"/invoices/{invoice_id}", headers=auth(tokens, organization_id))
        assert current.json() == invoice


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("exists", [False, True])
async def test_oversized_batch_etag_rejects_before_any_item_is_changed(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
    oversized_etag: str,
    position: int,
    exists: bool,
) -> None:
    invoices = [await create(client, tokens, organization_id) for _ in range(3)]
    items = [{"id": item["id"], "etag": item["etag"], "reason": "r"} for item in invoices]
    items[position]["etag"] = oversized_etag
    if not exists:
        items[position]["id"] = str(uuid4())

    response = await client.post(
        "/invoices/batch-void", json={"items": items}, headers=auth(tokens, organization_id)
    )

    problem = Problem.model_validate(response.json())
    assert (response.status_code, problem.code) == (400, "concurrency.invalid_if_match")
    assert problem.trace_id == response.headers["X-Trace-Id"]
    for invoice in invoices:
        current = await client.get(
            f"/invoices/{invoice['id']}", headers=auth(tokens, organization_id)
        )
        assert current.json() == invoice


@pytest.mark.parametrize("method", ["PATCH", "DELETE", "POST"])
@pytest.mark.parametrize("exists", [False, True])
async def test_convertible_large_if_match_keeps_resource_and_version_priority(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
    method: str,
    exists: bool,
) -> None:
    invoice = await create(client, tokens, organization_id) if exists else None
    invoice_id = invoice["id"] if invoice else str(uuid4())
    path = f"/invoices/{invoice_id}" + ("/void" if method == "POST" else "")

    response = await client.request(
        method,
        path,
        json={"reason": "r"} if method == "POST" else {},
        headers={**auth(tokens, organization_id), "If-Match": f'"{10**1000}"'},
    )

    expected = (412, "concurrency.etag_mismatch") if exists else (404, "billing.invoice.not_found")
    assert (response.status_code, response.json()["code"]) == expected


async def test_convertible_large_batch_etags_keep_ordered_per_item_outcomes(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
) -> None:
    stale = await create(client, tokens, organization_id)
    valid = await create(client, tokens, organization_id)
    large_etag = f'"{10**1000}"'
    items = [
        {"id": stale["id"], "etag": large_etag, "reason": "r"},
        {"id": str(uuid4()), "etag": large_etag, "reason": "r"},
        {"id": valid["id"], "etag": valid["etag"], "reason": "r"},
    ]

    response = await client.post(
        "/invoices/batch-void", json={"items": items}, headers=auth(tokens, organization_id)
    )

    assert response.status_code == 207
    results = response.json()["results"]
    assert [(item["index"], item["status"]) for item in results] == [(0, 412), (1, 404), (2, 200)]
    assert results[0]["error"]["code"] == "concurrency.etag_mismatch"
    assert results[1]["error"]["code"] == "billing.invoice.not_found"
    assert results[2]["data"]["id"] == valid["id"]
    assert results[2]["data"]["etag"] == '"2"'
