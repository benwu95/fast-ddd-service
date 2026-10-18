from typing import Any
from uuid import UUID, uuid4

import httpx2
from fast_ddd_port.testing import TokenFactory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import Infrastructure
from tests.support import ALL_PERMISSIONS

type Factory = async_sessionmaker[AsyncSession]


def auth(tokens: TokenFactory, org: UUID, *permissions: str) -> dict[str, str]:
    return tokens.authorization(organization_id=org, permissions=permissions or ALL_PERMISSIONS)


def invoice_body(**overrides: Any) -> dict[str, Any]:
    return {
        "number": "INV-" + uuid4().hex[:8],
        "customer": {"id": str(uuid4()), "name": "Acme", "taxId": "12345678"},
        "lines": [{"description": "Consulting", "quantity": 2, "unitPrice": "150.00"}],
        **overrides,
    }


async def create(
    client: httpx2.AsyncClient, tokens: TokenFactory, org: UUID, **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/invoices", json=invoice_body(**overrides), headers=auth(tokens, org)
    )
    assert response.status_code == 201, response.text
    return response.json()


def if_match(tokens: TokenFactory, org: UUID, etag: str) -> dict[str, str]:
    return {**auth(tokens, org), "If-Match": etag}


async def test_create_returns_location_etag_and_the_resource(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    invoice_id = uuid4()
    response = await client.post(
        "/invoices", json=invoice_body(id=str(invoice_id)), headers=auth(tokens, organization_id)
    )

    assert response.status_code == 201
    assert response.headers["Location"] == f"/invoices/{invoice_id}"
    assert response.headers["ETag"] == '"1"'
    body = response.json()
    assert body["id"] == str(invoice_id)
    assert body["etag"] == '"1"'
    assert (body["status"], body["total"], body["note"]) == ("active", "300.00", None)
    assert body["lines"] == [
        {"description": "Consulting", "quantity": 2, "unitPrice": "150.00", "amount": "300.00"}
    ]
    assert body["createdAt"].endswith("Z")
    assert body["customer"]["taxId"] == "12345678"


async def test_create_rejections(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    existing = await create(client, tokens, organization_id)
    headers = auth(tokens, organization_id)

    async def post(body: dict[str, Any]) -> httpx2.Response:
        return await client.post("/invoices", json=body, headers=headers)

    duplicate_id = await post(invoice_body(id=existing["id"]))
    duplicate_number = await post(invoice_body(number=existing["number"]))
    no_lines = await post(invoice_body(lines=[]))
    too_long = await post(invoice_body(number="N" * 31))
    numeric_price = await post(
        invoice_body(lines=[{"description": "x", "quantity": 1, "unitPrice": 1.5}])
    )
    unknown_field = await post(invoice_body(status="voided"))

    assert (duplicate_id.status_code, duplicate_id.json()["code"]) == (
        409,
        "billing.invoice.already_exists",
    )
    assert (duplicate_number.status_code, duplicate_number.json()["code"]) == (
        409,
        "billing.invoice.number_taken",
    )
    assert (no_lines.status_code, no_lines.json()["code"]) == (422, "billing.invoice.no_lines")
    assert too_long.status_code == 422
    assert too_long.json()["errors"] == [
        {
            "pointer": "#/number",
            "code": "validation.string_too_long",
            "params": {"maxLength": 30},
            "detail": "String should have at most 30 characters",
        }
    ]
    assert numeric_price.json()["errors"][0]["pointer"] == "#/lines/0/unitPrice"
    assert unknown_field.json()["errors"][0]["code"] == "validation.extra_forbidden"


async def test_request_shape_errors(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    headers = auth(tokens, organization_id)

    plain = await client.post(
        "/invoices", content="{}", headers={**headers, "Content-Type": "text/plain"}
    )
    malformed = await client.post(
        "/invoices", content="{", headers={**headers, "Content-Type": "application/json"}
    )

    assert (plain.status_code, plain.json()["code"]) == (415, "request.unsupported_media_type")
    assert (malformed.status_code, malformed.json()["code"]) == (400, "request.malformed_json")


async def test_authentication_and_permissions(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    anonymous = await client.get("/invoices")
    read_only = await client.post(
        "/invoices", json=invoice_body(), headers=auth(tokens, organization_id, "invoice:read")
    )

    assert (anonymous.status_code, anonymous.json()["code"]) == (401, "auth.unauthenticated")
    assert (read_only.status_code, read_only.json()["code"]) == (403, "auth.permission_denied")


async def test_get_hides_other_organizations_and_bad_ids(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    invoice = await create(client, tokens, organization_id)

    own = await client.get(f"/invoices/{invoice['id']}", headers=auth(tokens, organization_id))
    other = await client.get(f"/invoices/{invoice['id']}", headers=auth(tokens, uuid4()))
    bad_id = await client.get("/invoices/not-a-uuid", headers=auth(tokens, organization_id))

    assert (own.status_code, own.headers["ETag"]) == (200, '"1"')
    assert own.json() == invoice
    assert (other.status_code, other.json()["code"]) == (404, "billing.invoice.not_found")
    assert (bad_id.status_code, bad_id.json()["code"]) == (404, "request.route_not_found")


async def test_write_preconditions(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    invoice = await create(client, tokens, organization_id)
    path = f"/invoices/{invoice['id']}"
    headers = auth(tokens, organization_id)

    missing = await client.patch(path, json={}, headers=headers)
    wildcard = await client.patch(path, json={}, headers={**headers, "If-Match": "*"})
    weak = await client.delete(path, headers={**headers, "If-Match": 'W/"1"'})
    stale = await client.post(
        f"{path}/void", json={"reason": "x"}, headers={**headers, "If-Match": '"9"'}
    )
    unknown = await client.patch(
        f"/invoices/{uuid4()}", json={}, headers={**headers, "If-Match": '"9"'}
    )

    assert (missing.status_code, missing.json()["code"]) == (
        428,
        "concurrency.precondition_required",
    )
    assert (wildcard.status_code, wildcard.json()["code"]) == (400, "concurrency.invalid_if_match")
    assert weak.status_code == 400
    assert (stale.status_code, stale.json()["code"]) == (412, "concurrency.etag_mismatch")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "billing.invoice.not_found")


async def test_patch_keeps_what_was_not_sent_and_clears_explicit_nulls(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    invoice = await create(client, tokens, organization_id)
    path = f"/invoices/{invoice['id']}"

    async def patch(body: dict[str, Any], etag: str) -> httpx2.Response:
        return await client.patch(path, json=body, headers=if_match(tokens, organization_id, etag))

    noted = await patch({"note": "pay by Friday"}, '"1"')
    unchanged = await patch({}, '"2"')
    cleared = await patch({"note": None}, '"2"')
    customer = {"id": str(uuid4()), "name": "Beta"}
    replaced = await patch(
        {"customer": customer, "lines": [{"description": "x", "quantity": 1, "unitPrice": "5"}]},
        '"3"',
    )
    null_number = await patch({"number": None}, '"4"')

    assert (noted.status_code, noted.json()["note"], noted.headers["ETag"]) == (
        200,
        "pay by Friday",
        '"2"',
    )
    assert noted.json()["number"] == invoice["number"]
    assert unchanged.headers["ETag"] == '"2"'
    assert (cleared.json()["note"], cleared.headers["ETag"]) == (None, '"3"')
    assert replaced.json()["customer"] == {**customer, "taxId": None}
    assert replaced.json()["total"] == "5.00"
    assert null_number.status_code == 422


async def test_delete_and_void(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    organization_id: UUID,
    infrastructure: Infrastructure,
    session_factory: Factory,
) -> None:
    deleted = await create(client, tokens, organization_id)
    voided = await create(client, tokens, organization_id)

    delete = await client.delete(
        f"/invoices/{deleted['id']}", headers=if_match(tokens, organization_id, '"1"')
    )
    gone = await client.get(f"/invoices/{deleted['id']}", headers=auth(tokens, organization_id))
    void = await client.post(
        f"/invoices/{voided['id']}/void",
        json={"reason": "duplicate"},
        headers=if_match(tokens, organization_id, '"1"'),
    )
    again = await client.post(
        f"/invoices/{voided['id']}/void",
        json={"reason": "again"},
        headers=if_match(tokens, organization_id, '"2"'),
    )
    delete_voided = await client.delete(
        f"/invoices/{voided['id']}", headers=if_match(tokens, organization_id, '"2"')
    )

    assert (delete.status_code, gone.status_code) == (204, 404)
    assert void.status_code == 200
    assert (void.json()["status"], void.json()["voidReason"]) == ("voided", "duplicate")
    assert void.headers["ETag"] == '"2"'
    assert (again.status_code, again.json()["code"]) == (409, "billing.invoice.already_voided")
    assert again.json()["params"] == {
        "invoiceId": voided["id"],
        "voidedAt": void.json()["voidedAt"],
    }
    assert delete_voided.status_code == 409
    assert infrastructure.publisher.event_names() == [
        "InvoiceIssued",
        "InvoiceIssued",
        "InvoiceDeleted",
        "InvoiceVoided",
    ]
    async with session_factory() as session:
        jobs = (await session.execute(text("SELECT entrypoint FROM pgqueuer"))).scalars().all()
    assert jobs == ["billing.send_void_notice"]


async def test_batch_void_reports_each_item(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    ok, stale, voided = [await create(client, tokens, organization_id) for _ in range(3)]
    await client.post(
        f"/invoices/{voided['id']}/void",
        json={"reason": "x"},
        headers=if_match(tokens, organization_id, '"1"'),
    )
    missing = str(uuid4())

    response = await client.post(
        "/invoices/batch-void",
        json={
            "items": [
                {"id": ok["id"], "etag": '"1"', "reason": "r"},
                {"id": stale["id"], "etag": '"7"', "reason": "r"},
                {"id": voided["id"], "etag": '"2"', "reason": "r"},
                {"id": missing, "etag": '"1"', "reason": "r"},
            ]
        },
        headers=auth(tokens, organization_id),
    )

    assert response.status_code == 207
    results = response.json()["results"]
    assert [(r["index"], r["status"]) for r in results] == [(0, 200), (1, 412), (2, 409), (3, 404)]
    assert results[0]["data"]["status"] == "voided"
    assert [r["error"]["code"] for r in results[1:]] == [
        "concurrency.etag_mismatch",
        "billing.invoice.already_voided",
        "billing.invoice.not_found",
    ]


async def test_batch_void_rejects_duplicates_and_oversized_batches(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    item = {"id": str(uuid4()), "etag": '"1"', "reason": "r"}
    headers = auth(tokens, organization_id)

    duplicate = await client.post(
        "/invoices/batch-void", json={"items": [item, item]}, headers=headers
    )
    oversized = await client.post(
        "/invoices/batch-void",
        json={"items": [{**item, "id": str(uuid4())} for _ in range(101)]},
        headers=headers,
    )

    assert duplicate.status_code == 422
    assert duplicate.json()["errors"][0]["code"] == "validation.duplicate_id"
    assert duplicate.json()["errors"][0]["pointer"] == "#/items/1/id"
    assert (oversized.status_code, oversized.json()["errors"][0]["code"]) == (
        422,
        "validation.too_long",
    )


async def test_list_pages_filters_and_searches(
    client: httpx2.AsyncClient, tokens: TokenFactory, organization_id: UUID
) -> None:
    for number in ("INV-2", "INV-1", "CN-1"):
        await create(client, tokens, organization_id, number=number)
    await create(client, tokens, uuid4(), number="INV-0")
    headers = auth(tokens, organization_id)

    async def numbers(query: str) -> tuple[int, list[str]]:
        response = await client.get(f"/invoices?{query}", headers=headers)
        assert response.status_code == 200, response.text
        page = response.json()
        return page["total"], [item["number"] for item in page["items"]]

    assert await numbers("sortBy=number&limit=2") == (3, ["CN-1", "INV-1"])
    assert await numbers("sortBy=-number&offset=1&limit=1") == (3, ["INV-1"])
    assert await numbers("searchKeyField=starts:number&searchKey=CN") == (1, ["CN-1"])
    assert await numbers("searchKeyField=customerName&searchKey=Acme&status=voided") == (0, [])
    first = (await client.get("/invoices?limit=1", headers=headers)).json()["items"][0]
    assert first["etag"] == '"1"'

    for bad in ("limit=101", "sortBy=total", "searchKeyField=note", "foo=1"):
        response = await client.get(f"/invoices?{bad}", headers=headers)
        assert (response.status_code, response.json()["code"]) == (422, "validation.failed"), bad


async def test_openapi_is_ready_for_client_generation(client: httpx2.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    operations = {
        operation["operationId"]: operation
        for path in schema["paths"].values()
        for operation in path.values()
    }

    assert {
        "listInvoices",
        "getInvoice",
        "createInvoice",
        "updateInvoice",
        "deleteInvoice",
        "voidInvoice",
        "batchVoidInvoices",
    } <= operations.keys()
    for name in ("updateInvoice", "deleteInvoice", "voidInvoice"):
        if_match_header = next(p for p in operations[name]["parameters"] if p["name"] == "If-Match")
        assert if_match_header["required"] is True, name
    price = schema["components"]["schemas"]["InvoiceLineBody"]["properties"]["unitPrice"]
    assert (price["type"], price["format"]) == ("string", "decimal")
