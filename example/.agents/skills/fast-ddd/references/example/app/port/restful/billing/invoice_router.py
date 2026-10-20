from typing import Annotated
from uuid import UUID

from fast_ddd.batch import BatchItem
from fast_ddd_port.auth import require
from fast_ddd_port.http import BatchResponse, PageResponse, batch_response, ensure_unique_ids
from fast_ddd_port.preconditions import ExpectedVersion, parse_etag
from fastapi import APIRouter, Query, Response, status

from app.adapter.controller.billing.invoice_controller import InvoiceController
from app.core.billing.domain.invoice import InvoiceId
from app.port.restful.billing.invoice_schemas import (
    BatchVoidInvoicesRequest,
    CreateInvoiceRequest,
    InvoiceListQuery,
    InvoiceResponse,
    UpdateInvoiceRequest,
    VoidInvoiceRequest,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])
controller = InvoiceController()


def _respond(response: Response, invoice: InvoiceResponse) -> InvoiceResponse:
    response.headers["ETag"] = invoice.etag
    return invoice


@router.get("", dependencies=[require("invoice:read")])
async def list_invoices(
    query: Annotated[InvoiceListQuery, Query()],
) -> PageResponse[InvoiceResponse]:
    page = await controller.search(query.to_query())
    return PageResponse(
        total=page.total, items=[InvoiceResponse.from_domain(i) for i in page.items]
    )


@router.get("/{invoice_id:uuid}", dependencies=[require("invoice:read")])
async def get_invoice(invoice_id: UUID, response: Response) -> InvoiceResponse:
    invoice = await controller.get(InvoiceId(invoice_id))
    return _respond(response, InvoiceResponse.from_domain(invoice))


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[require("invoice:create")])
async def create_invoice(body: CreateInvoiceRequest, response: Response) -> InvoiceResponse:
    invoice = await controller.create(body.to_command())
    response.headers["Location"] = f"{router.prefix}/{invoice.id}"
    return _respond(response, InvoiceResponse.from_domain(invoice))


@router.patch("/{invoice_id:uuid}", dependencies=[require("invoice:update")])
async def update_invoice(
    invoice_id: UUID,
    body: UpdateInvoiceRequest,
    expected_version: ExpectedVersion,
    response: Response,
) -> InvoiceResponse:
    invoice = await controller.update(body.to_command(invoice_id, expected_version))
    return _respond(response, InvoiceResponse.from_domain(invoice))


@router.delete(
    "/{invoice_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require("invoice:delete")],
)
async def delete_invoice(invoice_id: UUID, expected_version: ExpectedVersion) -> None:
    await controller.delete(InvoiceId(invoice_id), expected_version)


@router.post("/{invoice_id:uuid}/void", dependencies=[require("invoice:void")])
async def void_invoice(
    invoice_id: UUID,
    body: VoidInvoiceRequest,
    expected_version: ExpectedVersion,
    response: Response,
) -> InvoiceResponse:
    invoice = await controller.void(InvoiceId(invoice_id), body.reason, expected_version)
    return _respond(response, InvoiceResponse.from_domain(invoice))


@router.post(
    "/batch-void",
    status_code=status.HTTP_207_MULTI_STATUS,
    dependencies=[require("invoice:void")],
)
async def batch_void_invoices(body: BatchVoidInvoicesRequest) -> BatchResponse[InvoiceResponse]:
    ensure_unique_ids([item.id for item in body.items])
    items = [
        BatchItem(InvoiceId(item.id), item.reason, expected_version=parse_etag(item.etag))
        for item in body.items
    ]
    outcome = await controller.void_many(items)
    return batch_response(items, outcome, InvoiceResponse.from_domain)
