import asyncio
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
import uvicorn
from fast_ddd_adapter.observability import Telemetry
from fastapi.routing import iter_route_contexts
from pgqueuer import PgQueuer

from app import task_worker
from app.bootstrap import Runtime
from tests.runtime.support import runtime, settings


async def test_signal_drains_in_flight_work_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = runtime()
    worker = Mock(spec=PgQueuer)
    worker.shutdown = asyncio.Event()
    stop = asyncio.Event()
    health = Mock(spec=uvicorn.Server)
    health.should_exit = False
    finished: list[str] = []

    async def run_worker(**_: object) -> None:
        stop.set()
        await worker.shutdown.wait()
        await asyncio.sleep(0.01)
        finished.append("completed")

    async def run_health() -> None:
        await worker.shutdown.wait()

    worker.run = AsyncMock(side_effect=run_worker)
    health.serve = AsyncMock(side_effect=run_health)
    monkeypatch.setattr(task_worker, "_HealthServer", Mock(return_value=health))
    await task_worker.serve_worker(cast(Runtime, resources), cast(PgQueuer, worker), stop)
    assert finished == ["completed"]


async def test_drain_timeout_cancels_unresponsive_worker_and_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = runtime()
    worker = Mock(spec=PgQueuer)
    worker.shutdown = asyncio.Event()
    stop = asyncio.Event()
    health = Mock(spec=uvicorn.Server)
    health.should_exit = False
    cancelled: list[str] = []

    async def run_worker(**_: object) -> None:
        stop.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append("worker")

    async def run_health() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append("health")

    worker.run = AsyncMock(side_effect=run_worker)
    health.serve = AsyncMock(side_effect=run_health)
    monkeypatch.setattr(task_worker, "_HealthServer", Mock(return_value=health))
    serving = asyncio.create_task(
        task_worker.serve_worker(cast(Runtime, resources), cast(PgQueuer, worker), stop)
    )
    try:
        done, _ = await asyncio.wait({serving}, timeout=1)
        assert serving in done, "worker drain exceeded its configured shutdown timeout"
        with pytest.raises(TimeoutError):
            await serving
    finally:
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)
    assert sorted(cancelled) == ["health", "worker"]


async def test_worker_role_health_tracks_its_task_and_exposes_no_business_routes(
    engine: object,
) -> None:
    import httpx2

    resources = runtime()
    resources.engine = engine

    async def work() -> None:
        await asyncio.Event().wait()

    running = asyncio.create_task(work())
    app = task_worker.build_health_app(cast(Runtime, resources), running)
    try:
        assert {
            (route.path, frozenset(route.methods or ()))
            for route in iter_route_contexts(app.routes)
        } == {
            ("/health/live", frozenset({"GET"})),
            ("/health/ready", frozenset({"GET"})),
        }
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://worker.test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            assert (await client.get("/health/ready")).status_code == 200
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
            assert (await client.get("/health/live")).status_code == 503
            assert (await client.get("/health/ready")).status_code == 503
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


async def test_run_worker_installs_signals_and_closes_all_resources_after_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = runtime()
    telemetry = Mock(spec=Telemetry)
    connection = Mock()
    connection.close = AsyncMock()
    worker = Mock(spec=PgQueuer)
    handlers: list[object] = []
    loop = asyncio.get_running_loop()

    def install_handler(_signal: int, handler: object) -> None:
        handlers.append(handler)

    install = Mock(side_effect=install_handler)
    remove = Mock()
    monkeypatch.setattr(loop, "add_signal_handler", install)
    monkeypatch.setattr(loop, "remove_signal_handler", remove)
    monkeypatch.setattr(task_worker, "configure_process", Mock(return_value=telemetry))
    monkeypatch.setattr(task_worker, "build_runtime", Mock(return_value=resources))
    monkeypatch.setattr(task_worker.asyncpg, "connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(task_worker, "build_task_worker", Mock(return_value=worker))

    async def serve(_: Runtime, __: PgQueuer, stop: asyncio.Event) -> None:
        install.call_args_list[0].args[1]()
        assert stop.is_set()

    monkeypatch.setattr(task_worker, "serve_worker", serve)
    await task_worker.run_worker(resources.settings)
    assert len(handlers) == 2
    assert remove.call_count == 2
    connection.close.assert_awaited_once()
    resources.broker.stop.assert_awaited_once()
    resources.close.assert_awaited_once()
    telemetry.shutdown.assert_called_once()


async def test_main_loads_settings_and_runs_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = settings()
    run = AsyncMock()
    monkeypatch.setattr(task_worker, "load_settings", Mock(return_value=configured))
    monkeypatch.setattr(task_worker, "run_worker", run)
    await task_worker.main()
    run.assert_awaited_once_with(configured)
