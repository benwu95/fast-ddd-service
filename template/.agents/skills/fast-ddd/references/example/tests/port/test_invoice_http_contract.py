from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from fast_ddd_port.http import BatchResponse, PageResponse
from fast_ddd_port.problems import Problem
from fast_ddd_port.testing import TokenFactory

from app.port.restful.billing.invoice_router import controller
from app.port.restful.billing.invoice_schemas import InvoiceResponse
from tests.port.test_invoice_api import auth, create, if_match, invoice_body
from tests.support import FRONTEND


async def test_all_seven_operations_match_their_success_and_problem_contracts(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
) -> None:
    schema = (await client.get("/openapi.json")).json()
    operations = {
        operation["operationId"]: operation
        for path in schema["paths"].values()
        for operation in path.values()
    }
    headers = {**auth(tokens, organization_id), "Origin": FRONTEND}
    created = await client.post("/invoices", json=invoice_body(), headers=headers)
    invoice = created.json()
    resource = f"/invoices/{invoice['id']}"
    success: dict[str, httpx2.Response] = {"createInvoice": created}
    success["listInvoices"] = await client.get("/invoices", headers=headers)
    success["getInvoice"] = await client.get(resource, headers=headers)
    success["updateInvoice"] = await client.patch(
        resource,
        json={"note": "updated"},
        headers={**headers, "If-Match": '"1"'},
    )
    success["voidInvoice"] = await client.post(
        f"{resource}/void",
        json={"reason": "duplicate"},
        headers={**headers, "If-Match": '"2"'},
    )
    batch_invoices = [await create(client, tokens, organization_id) for _ in range(2)]
    batch_order = list(reversed(batch_invoices))
    success["batchVoidInvoices"] = await client.post(
        "/invoices/batch-void",
        json={
            "items": [
                {"id": item["id"], "etag": item["etag"], "reason": "r"} for item in batch_order
            ],
        },
        headers=headers,
    )
    batch = success["batchVoidInvoices"]
    assert batch.status_code == 207
    assert [
        (item["index"], item["status"], item["data"]["id"]) for item in batch.json()["results"]
    ] == [(index, 200, item["id"]) for index, item in enumerate(batch_order)]
    deletable = await create(client, tokens, organization_id)
    success["deleteInvoice"] = await client.delete(
        f"/invoices/{deletable['id']}",
        headers={**headers, "If-Match": '"1"'},
    )
    for name, response in success.items():
        declared = operations[name]["responses"][str(response.status_code)]
        assert response.headers["X-Trace-Id"]
        assert "X-Trace-Id" in declared["headers"]
        exposed = {
            part.strip().lower()
            for part in response.headers["access-control-expose-headers"].split(",")
        }
        assert {"etag", "location", "x-trace-id", "retry-after"} <= exposed
        if response.status_code == 204:
            assert response.content == b""
            assert "content" not in declared
        else:
            assert response.headers["content-type"] == "application/json"
            assert declared["content"]["application/json"]["schema"]["$ref"]
            if name == "listInvoices":
                PageResponse[InvoiceResponse].model_validate(response.json())
            elif name == "batchVoidInvoices":
                BatchResponse[InvoiceResponse].model_validate(response.json())
            else:
                InvoiceResponse.model_validate(response.json())
                assert response.headers["ETag"] == response.json()["etag"]
                assert "ETag" in declared["headers"]
        if response.status_code == 201:
            assert response.headers["Location"] == resource
            assert "Location" in declared["headers"]

    requests: list[tuple[str, str, Any]] = [
        ("listInvoices", "/invoices", None),
        ("getInvoice", resource, None),
        ("createInvoice", "/invoices", invoice_body()),
        ("updateInvoice", resource, {}),
        ("deleteInvoice", resource, None),
        ("voidInvoice", f"{resource}/void", {"reason": "r"}),
        ("batchVoidInvoices", "/invoices/batch-void", {"items": []}),
    ]
    methods = ["GET", "GET", "POST", "PATCH", "DELETE", "POST", "POST"]
    for (name, path, body), method in zip(requests, methods, strict=True):
        response = await client.request(method, path, json=body)
        assert response.status_code == 401
        problem = Problem.model_validate(response.json())
        assert problem.code == "auth.unauthenticated"
        assert problem.trace_id == response.headers["X-Trace-Id"]
        declared = operations[name]["responses"]["401"]
        assert declared["content"] == {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}},
        }
        assert response.headers["content-type"] == "application/problem+json"
        assert "WWW-Authenticate" in declared["headers"]


@pytest.mark.parametrize("method", ["PATCH", "DELETE", "POST"])
@pytest.mark.parametrize(
    ("etag", "status"), [(None, 428), ("*", 400), ('W/"1"', 400), ('"9"', 404)]
)
async def test_absent_resource_precondition_priority(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
    method: str,
    etag: str | None,
    status: int,
) -> None:
    path = f"/invoices/{uuid4()}" + ("/void" if method == "POST" else "")
    headers = auth(tokens, organization_id)
    if etag is not None:
        headers["If-Match"] = etag
    response = await client.request(
        method, path, json={"reason": "r"} if method == "POST" else {}, headers=headers
    )
    assert response.status_code == status
    Problem.model_validate(response.json())


async def test_tenant_visibility_precedes_version_comparison(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
) -> None:
    invoice = await create(client, tokens, organization_id)
    for method, suffix, body in [
        ("PATCH", "", {}),
        ("DELETE", "", None),
        ("POST", "/void", {"reason": "r"}),
    ]:
        response = await client.request(
            method,
            f"/invoices/{invoice['id']}{suffix}",
            json=body,
            headers=if_match(tokens, uuid4(), '"999"'),
        )
        assert (response.status_code, response.json()["code"]) == (404, "billing.invoice.not_found")
    still_visible = await client.get(
        f"/invoices/{invoice['id']}", headers=auth(tokens, organization_id)
    )
    assert still_visible.json() == invoice


async def test_nested_patch_replaces_whole_value_and_rejects_null_collections(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
) -> None:
    invoice = await create(client, tokens, organization_id)
    path = f"/invoices/{invoice['id']}"
    replacement = {"id": str(uuid4()), "name": "new customer"}
    replaced = await client.patch(
        path, json={"customer": replacement}, headers=if_match(tokens, organization_id, '"1"')
    )
    assert replaced.status_code == 200
    assert replaced.json()["customer"] == {**replacement, "taxId": None}
    assert replaced.json()["lines"] == invoice["lines"]
    for body in ({"customer": None}, {"lines": None}, {"customer": {"name": "partial"}}):
        invalid = await client.patch(
            path, json=body, headers=if_match(tokens, organization_id, '"2"')
        )
        assert invalid.status_code == 422
    current = await client.get(path, headers=auth(tokens, organization_id))
    assert current.json() == replaced.json()


async def test_method_not_allowed_uses_problem_contract(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
) -> None:
    response = await client.put("/invoices", json={}, headers=auth(tokens, organization_id))
    assert (response.status_code, response.json()["code"]) == (405, "request.method_not_allowed")
    assert "POST" in response.headers["Allow"] or "GET" in response.headers["Allow"]
    assert response.headers["content-type"] == "application/problem+json"
    assert Problem.model_validate(response.json()).trace_id == response.headers["X-Trace-Id"]


async def test_service_failure_keeps_cors_trace_and_hides_internal_details(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*_: object) -> None:
        raise RuntimeError("private backend details")

    monkeypatch.setattr(controller, "search", fail)
    response = await client.get(
        "/invoices", headers={**auth(tokens, organization_id), "Origin": FRONTEND}
    )
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert Problem.model_validate(response.json()).trace_id == response.headers["X-Trace-Id"]
    assert response.json()["code"] == "server.internal_error"
    assert "private backend details" not in response.text
