import asyncio
from collections.abc import Callable, Sequence
from uuid import UUID

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.batch import BatchItem
from fast_ddd.errors import DomainError
from fast_ddd.serialization import to_camel
from fast_ddd_adapter.controller import BatchOutcome, UnexpectedFailure
from fast_ddd_port.auth import JwtVerifier
from fast_ddd_port.middleware import TRACE_HEADER, UnitOfWorkMiddleware
from fast_ddd_port.models import ResponseModel
from fast_ddd_port.preconditions import install_openapi_fixups
from fast_ddd_port.problems import (
    Problem,
    duplicate_id_problem,
    install_problem_handlers,
    kernel_problem,
    outcome_problem,
    problem_response,
)
from fast_ddd_port.settings import KernelSettings


def operation_id(route: APIRoute) -> str:
    """``generate_unique_id_function``: route function ``void_order`` becomes ``voidOrder``."""
    return to_camel(route.name)


MAX_BATCH_ITEMS = 100
"""Default ``max_length`` for batch ``items`` (and the list ``limit``); it bounds locked rows."""


class PageResponse[T: ResponseModel](ResponseModel):
    """One page of a list endpoint (offset + limit); ``total`` counts every match."""

    total: int
    items: list[T]


class BatchResultItem[T: ResponseModel](ResponseModel):
    index: int
    status: int
    data: T | None = None
    error: Problem | None = None


class BatchResponse[T: ResponseModel](ResponseModel):
    results: list[BatchResultItem[T]] = Field(default_factory=list[BatchResultItem[T]])


def ensure_unique_ids(ids: Sequence[UUID]) -> None:
    seen: set[UUID] = set()
    duplicates: list[int] = []
    for index, item_id in enumerate(ids):
        if item_id in seen:
            duplicates.append(index)
        seen.add(item_id)
    if duplicates:
        raise duplicate_id_problem(duplicates)


def batch_response[Id: UUID, A: AggregateRoot, T: ResponseModel, P](
    items: Sequence[BatchItem[Id, P]],
    outcome: BatchOutcome[Id, A],
    to_response: Callable[[A], T],
    success_status: int = 200,
) -> BatchResponse[T]:
    results: list[BatchResultItem[T]] = []
    for index, item in enumerate(items):
        result = outcome.results[item.id]
        if isinstance(result, DomainError | UnexpectedFailure):
            problem = outcome_problem(result)
            results.append(BatchResultItem[T](index=index, status=problem.status, error=problem))
        elif success_status == 204:
            results.append(BatchResultItem[T](index=index, status=204))
        else:
            results.append(
                BatchResultItem[T](index=index, status=success_status, data=to_response(result))
            )
    return BatchResponse[T](results=results)


def health_router(
    engine: AsyncEngine,
    *,
    is_alive: Callable[[], bool] | None = None,
    timeout_seconds: float = 5.0,
) -> APIRouter:
    async def live() -> dict[str, str] | JSONResponse:
        if is_alive is not None and not is_alive():
            return problem_response(kernel_problem("server.unavailable"))
        return {"status": "ok"}

    async def ready() -> dict[str, str] | JSONResponse:
        if is_alive is not None and not is_alive():
            return problem_response(kernel_problem("server.unavailable"))
        try:
            async with asyncio.timeout(timeout_seconds), engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            return problem_response(kernel_problem("server.unavailable"))
        return {"status": "ok"}

    router = APIRouter(tags=["health"])
    router.add_api_route(
        "/health/live", live, methods=["GET"], include_in_schema=False, response_model=None
    )
    router.add_api_route(
        "/health/ready", ready, methods=["GET"], include_in_schema=False, response_model=None
    )
    return router


def install_kernel(
    app: FastAPI,
    *,
    settings: KernelSettings,
    verifier: JwtVerifier,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Problem handlers, unit-of-work middleware, CORS, health, OpenAPI fixups, tracing.

    Middleware order, outermost first: OpenTelemetry, CORS, unit of work.
    """
    install_problem_handlers(app)
    app.add_middleware(
        UnitOfWorkMiddleware,
        verifier=verifier,
        session_factory=session_factory,
        public_paths=settings.public_paths,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "If-Match"],
        expose_headers=["ETag", "Location", TRACE_HEADER, "Retry-After"],
    )
    app.include_router(health_router(engine))
    install_openapi_fixups(app)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health/live,/health/ready")
