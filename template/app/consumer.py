"""MQ consumer entry point: ``faststream run --factory app.consumer:create_app``."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fast_ddd_adapter.observability import configure_logging
from fast_ddd_port.settings import load_settings
from fast_ddd_port.subscriber import declare_dead_letter_queue
from faststream.asgi import AsgiFastStream, make_ping_asgi

from app.bootstrap import Runtime, build_runtime, configure_process
from app.settings import Settings
from app.wiring import wire_consumer

PING_TIMEOUT_SECONDS = 5.0
logger = logging.getLogger(__name__)


def build_consumer(runtime: Runtime) -> AsgiFastStream:
    queues = wire_consumer(runtime.broker, runtime.session_factory)

    @asynccontextmanager
    async def logging_lifespan() -> AsyncGenerator[None]:
        # FastStream creates its Uvicorn config after the application factory returns.
        try:
            configure_logging(runtime.settings.log_level)
            yield
        except Exception:
            logger.exception("consumer lifecycle failed")
            raise
        finally:
            await runtime.close()

    async def declare_dead_letter_queues() -> None:
        for queue in queues:
            await declare_dead_letter_queue(runtime.broker, queue)

    return AsgiFastStream(
        runtime.broker,
        asgi_routes=[
            ("/health/live", make_ping_asgi(runtime.broker, timeout=PING_TIMEOUT_SECONDS))
        ],
        lifespan=logging_lifespan,
        after_startup=[declare_dead_letter_queues],
    )


def create_app() -> AsgiFastStream:
    settings = load_settings(Settings)
    runtime = build_runtime(settings, role="consumer")
    app = build_consumer(runtime)
    telemetry = configure_process(settings)

    async def shutdown_telemetry() -> None:
        telemetry.shutdown()

    runtime.closers.insert(0, shutdown_telemetry)
    return app
