"""A small HTTP app over the test Order aggregate, wired the way a service's main.py would be."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Response
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fast_ddd.batch import BatchItem
from fast_ddd.context import current_organization_id
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.controller import execute, run_batch
from fast_ddd_adapter.infrastructure import configure
from fast_ddd_port.auth import require
from fast_ddd_port.http import (
    MAX_BATCH_ITEMS,
    BatchResponse,
    batch_response,
    ensure_unique_ids,
    install_kernel,
    operation_id,
)
from fast_ddd_port.models import RequestModel, ResponseModel, Timestamp, etag_of
from fast_ddd_port.preconditions import ExpectedVersion, parse_etag
from fast_ddd_port.settings import JwtSettings, KernelSettings
from fast_ddd_port.testing import TokenFactory
from tests.adapter.models import Order, OrderRepository
from tests.adapter.use_cases import OrderUseCase

FRONTEND = "https://frontend.test"
JWT_SETTINGS = JwtSettings(
    issuer="https://issuer.test",
    audience="kernel-tests",
    jwks_url="https://issuer.test/jwks",
    user_id_claim="sub",
    organization_id_claim="org",
    permissions_claim="scope",
    permissions_format="space_separated",
)


class CreateOrderRequest(RequestModel):
    id: UUID | None = None
    code: Annotated[str, Field(min_length=1, max_length=50)]


class VoidOrderRequest(RequestModel):
    reason: Annotated[str, Field(max_length=200)]


class BatchVoidItem(RequestModel):
    id: UUID
    etag: str
    reason: Annotated[str, Field(max_length=200)]


class BatchVoidRequest(RequestModel):
    items: Annotated[list[BatchVoidItem], Field(min_length=1, max_length=MAX_BATCH_ITEMS)]


class OrderResponse(ResponseModel):
    id: UUID
    code: str
    status: str
    etag: str
    created_at: Timestamp
    updated_at: Timestamp

    @classmethod
    def from_domain(cls, order: Order) -> "OrderResponse":
        return cls(
            id=order.id,
            code=order.code,
            status=order.status.value,
            etag=etag_of(order.version),
            created_at=order.created_at,
            updated_at=order.updated_at,
        )


def _use_case() -> OrderUseCase:
    return OrderUseCase(OrderRepository())


def _with_etag(response: Response, order: Order) -> OrderResponse:
    response.headers["ETag"] = etag_of(order.version)
    return OrderResponse.from_domain(order)


def order_router() -> APIRouter:
    router = APIRouter(prefix="/orders", tags=["orders"])

    async def create_order(body: CreateOrderRequest, response: Response) -> OrderResponse:
        organization_id = current_organization_id()
        assert organization_id is not None
        order_id = body.id or uuid4()
        order = await execute(lambda: _use_case().create(order_id, organization_id, body.code))
        response.headers["Location"] = f"/orders/{order.id}"
        return _with_etag(response, order)

    async def get_order(order_id: UUID, response: Response) -> OrderResponse:
        order = await execute(lambda: OrderRepository().load(order_id, lock=False))
        return _with_etag(response, order)

    async def void_order(
        order_id: UUID,
        body: VoidOrderRequest,
        expected_version: ExpectedVersion,
        response: Response,
    ) -> OrderResponse:
        order = await execute(lambda: _use_case().void(order_id, body.reason, expected_version))
        return _with_etag(response, order)

    async def batch_void_orders(body: BatchVoidRequest) -> BatchResponse[OrderResponse]:
        ensure_unique_ids([item.id for item in body.items])
        items = [BatchItem(i.id, i.reason, expected_version=parse_etag(i.etag)) for i in body.items]
        outcome = await run_batch(
            items,
            batch=_use_case().void_many,
            single=lambda i: _use_case().void(i.id, i.payload, i.expected_version),
        )
        return batch_response(items, outcome, OrderResponse.from_domain)

    async def boom() -> None:
        raise RuntimeError("unexpected")

    router.add_api_route(
        "", create_order, methods=["POST"], status_code=201,
        dependencies=[require("order:create")],
    )  # fmt: skip
    router.add_api_route(
        "/{order_id:uuid}", get_order, methods=["GET"], dependencies=[require("order:read")]
    )
    router.add_api_route(
        "/{order_id:uuid}/void", void_order, methods=["POST"],
        dependencies=[require("order:void")],
    )  # fmt: skip
    router.add_api_route(
        "/batch-void", batch_void_orders, methods=["POST"], status_code=207,
        dependencies=[require("order:void")],
    )  # fmt: skip
    router.add_api_route("/boom", boom, methods=["GET"], dependencies=[require("order:read")])
    return router


def build_app(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    tokens: TokenFactory,
) -> FastAPI:
    settings = KernelSettings(
        service_name="kernel-tests",
        database_url="unused",
        jwt=JWT_SETTINGS,
        cors_allow_origins=[FRONTEND],
    )
    configure(session_factory=session_factory, event_bus=EventBus())
    app = FastAPI(generate_unique_id_function=operation_id)
    install_kernel(
        app,
        settings=settings,
        verifier=tokens.verifier(),
        engine=engine,
        session_factory=session_factory,
    )
    app.include_router(order_router())
    return app
