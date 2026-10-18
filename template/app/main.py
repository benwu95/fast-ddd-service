"""API entry point: ``uvicorn --factory app.main:create_app``."""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fast_ddd_adapter.http_client import create_http_client
from fast_ddd_port.auth import JwtVerifier
from fast_ddd_port.http import install_kernel, operation_id
from fast_ddd_port.settings import load_settings
from fastapi import FastAPI

from app.bootstrap import Runtime, build_runtime, configure_process
from app.settings import Settings
from app.wiring import wire_http

JWKS_TIMEOUT_SECONDS = 5.0


def build_app(runtime: Runtime, verifier: JwtVerifier) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        # Publish only: subscribers are registered by the consumer process, never here.
        async with AsyncExitStack() as stack:
            stack.push_async_callback(runtime.close)
            stack.push_async_callback(runtime.broker.stop)
            await runtime.broker.connect()
            yield

    app = FastAPI(
        title=runtime.settings.service_name,
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )
    install_kernel(
        app,
        settings=runtime.settings,
        verifier=verifier,
        engine=runtime.engine,
        session_factory=runtime.session_factory,
    )
    wire_http(app)
    return app


def create_app() -> FastAPI:
    settings = load_settings(Settings)
    runtime = build_runtime(settings, role="api")
    jwks_http = create_http_client("jwks", base_url="", timeout=JWKS_TIMEOUT_SECONDS)

    async def shutdown_telemetry() -> None:
        telemetry.shutdown()

    runtime.closers.append(jwks_http.aclose)
    app = build_app(runtime, JwtVerifier(settings.jwt, jwks_http))
    telemetry = configure_process(settings)
    runtime.closers.insert(0, shutdown_telemetry)
    return app
