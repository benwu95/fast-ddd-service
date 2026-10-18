"""Background task worker entry point: ``python -m app.task_worker``."""

import asyncio
import math
import signal
from collections.abc import Generator
from contextlib import AsyncExitStack, contextmanager

import asyncpg
import uvicorn
from fast_ddd_port.http import health_router
from fast_ddd_port.settings import load_settings
from fast_ddd_port.tasks import TaskRegistry, build_worker
from fastapi import FastAPI
from pgqueuer import PgQueuer
from sqlalchemy import make_url

from app.bootstrap import Runtime, build_runtime, configure_process
from app.settings import Settings
from app.wiring import wire_tasks


class _HealthServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Generator[None]:
        # The composition root owns signals for both the worker and probe server.
        yield


def driver_dsn(database_url: str) -> str:
    """PgQueuer listens on its own asyncpg connection, which takes a plain ``postgresql://``."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(False)


def build_task_worker(runtime: Runtime, connection: asyncpg.Connection) -> PgQueuer:
    registry = TaskRegistry()
    wire_tasks(registry)
    return build_worker(connection, registry, runtime.session_factory)


def build_health_app(runtime: Runtime, worker_task: asyncio.Task[None]) -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.include_router(
        health_router(
            runtime.engine,
            is_alive=lambda: not worker_task.done(),
            timeout_seconds=runtime.settings.worker_health_timeout_seconds,
        )
    )
    return app


async def _cancel_task[T](task: asyncio.Task[T]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def serve_worker(runtime: Runtime, worker: PgQueuer, stop: asyncio.Event) -> None:
    settings = runtime.settings
    async with AsyncExitStack() as stack:
        worker_task = asyncio.create_task(worker.run(shutdown_on_listener_failure=True))
        stack.push_async_callback(_cancel_task, worker_task)
        stack.callback(worker.shutdown.set)
        server = _HealthServer(
            uvicorn.Config(
                build_health_app(runtime, worker_task),
                host=settings.worker_health_host,
                port=settings.worker_health_port,
                log_config=None,
                timeout_graceful_shutdown=math.ceil(settings.worker_shutdown_timeout_seconds),
            )
        )
        health_task = asyncio.create_task(server.serve())
        stack.push_async_callback(_cancel_task, health_task)
        stop_task = asyncio.create_task(stop.wait())
        stack.push_async_callback(_cancel_task, stop_task)
        try:
            done, _ = await asyncio.wait(
                (worker_task, health_task, stop_task), return_when=asyncio.FIRST_COMPLETED
            )
            for task in (worker_task, health_task):
                if task in done:
                    await task
                    raise RuntimeError("worker component stopped unexpectedly")
        finally:
            worker.shutdown.set()
            server.should_exit = True
            stop_task.cancel()
            await asyncio.wait_for(
                asyncio.gather(worker_task, health_task, return_exceptions=True),
                timeout=settings.worker_shutdown_timeout_seconds,
            )


async def run_worker(settings: Settings) -> None:
    telemetry = configure_process(settings)
    async with AsyncExitStack() as stack:
        stack.callback(telemetry.shutdown)
        runtime = build_runtime(settings, role="worker")
        stack.push_async_callback(runtime.close)
        stack.push_async_callback(runtime.broker.stop)
        await runtime.broker.connect()
        connection = await asyncpg.connect(driver_dsn(settings.database_url))
        stack.push_async_callback(connection.close)
        worker = build_task_worker(runtime, connection)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for stop_signal in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(stop_signal, stop.set)
            stack.callback(loop.remove_signal_handler, stop_signal)
        await serve_worker(runtime, worker, stop)


async def main() -> None:
    await run_worker(load_settings(Settings))


if __name__ == "__main__":
    asyncio.run(main())
