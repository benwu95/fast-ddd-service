import asyncio
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
import uvicorn
from fast_ddd_adapter.observability import Telemetry
from pgqueuer import PgQueuer

from app import task_worker
from app.bootstrap import Runtime
from tests.runtime.support import runtime, settings


async def test_connection_failure_closes_previously_created_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = runtime()
    telemetry = Mock(spec=Telemetry)
    monkeypatch.setattr(task_worker, "configure_process", Mock(return_value=telemetry))
    monkeypatch.setattr(task_worker, "build_runtime", Mock(return_value=resources))
    monkeypatch.setattr(task_worker.asyncpg, "connect", AsyncMock(side_effect=OSError("DB down")))
    with pytest.raises(OSError, match="DB down"):
        await task_worker.run_worker(resources.settings)
    resources.broker.stop.assert_awaited_once()
    resources.close.assert_awaited_once()
    telemetry.shutdown.assert_called_once()


async def test_broker_start_failure_still_stops_broker_and_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = runtime()
    resources.broker.connect.side_effect = OSError("broker down")
    telemetry = Mock(spec=Telemetry)
    monkeypatch.setattr(task_worker, "configure_process", Mock(return_value=telemetry))
    monkeypatch.setattr(task_worker, "build_runtime", Mock(return_value=resources))
    with pytest.raises(OSError, match="broker down"):
        await task_worker.run_worker(resources.settings)
    resources.broker.stop.assert_awaited_once()
    resources.close.assert_awaited_once()
    telemetry.shutdown.assert_called_once()


async def test_worker_build_failure_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = runtime()
    telemetry = Mock(spec=Telemetry)
    connection = Mock()
    connection.close = AsyncMock()
    monkeypatch.setattr(task_worker, "configure_process", Mock(return_value=telemetry))
    monkeypatch.setattr(task_worker, "build_runtime", Mock(return_value=resources))
    monkeypatch.setattr(task_worker.asyncpg, "connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(task_worker, "build_task_worker", Mock(side_effect=ValueError("registry")))
    with pytest.raises(ValueError, match="registry"):
        await task_worker.run_worker(resources.settings)
    connection.close.assert_awaited_once()
    resources.broker.stop.assert_awaited_once()
    resources.close.assert_awaited_once()
    telemetry.shutdown.assert_called_once()


@pytest.mark.parametrize("failure", ["worker", "health"])
async def test_component_failure_stops_the_other_component(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    resources = runtime()
    worker = Mock(spec=PgQueuer)
    worker.shutdown = asyncio.Event()
    health = Mock(spec=uvicorn.Server)
    health.should_exit = False
    closed: list[str] = []

    async def run_worker(**_: object) -> None:
        try:
            if failure == "worker":
                raise RuntimeError("worker failed")
            await worker.shutdown.wait()
        finally:
            closed.append("worker")

    async def run_health() -> None:
        try:
            if failure == "health":
                raise RuntimeError("health failed")
            await worker.shutdown.wait()
        finally:
            closed.append("health")

    worker.run = AsyncMock(side_effect=run_worker)
    health.serve = AsyncMock(side_effect=run_health)
    monkeypatch.setattr(task_worker, "_HealthServer", Mock(return_value=health))
    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        await task_worker.serve_worker(
            cast(Runtime, resources), cast(PgQueuer, worker), asyncio.Event()
        )
    assert worker.shutdown.is_set()
    assert health.should_exit
    assert sorted(closed) == ["health", "worker"]


async def test_runtime_closes_all_resources_even_when_one_close_fails() -> None:
    engine = Mock()
    engine.dispose = AsyncMock()
    first, failing = AsyncMock(), AsyncMock(side_effect=OSError("close failed"))
    resources = Runtime(settings(), engine, Mock(), Mock(), [first, failing])
    with pytest.raises(OSError, match="close failed"):
        await resources.close()
    first.assert_awaited_once()
    engine.dispose.assert_awaited_once()


async def test_runtime_build_failure_still_stops_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry = Mock(spec=Telemetry)
    monkeypatch.setattr(task_worker, "configure_process", Mock(return_value=telemetry))
    monkeypatch.setattr(task_worker, "build_runtime", Mock(side_effect=ValueError("runtime")))
    with pytest.raises(ValueError, match="runtime"):
        await task_worker.run_worker(settings())
    telemetry.shutdown.assert_called_once()


@pytest.mark.parametrize("failure", ["config", "application", "server"])
async def test_health_server_construction_failure_leaves_no_worker_task(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    resources = runtime()
    worker = Mock(spec=PgQueuer)
    worker.shutdown = asyncio.Event()

    async def run(**_: object) -> None:
        await asyncio.Event().wait()

    worker.run = AsyncMock(side_effect=run)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    if failure == "config":
        monkeypatch.setenv("WEB_CONCURRENCY", "invalid")
    elif failure == "application":
        monkeypatch.setattr(task_worker, "build_health_app", Mock(side_effect=ValueError("app")))
    else:
        monkeypatch.setattr(task_worker, "_HealthServer", Mock(side_effect=ValueError("server")))
    before = set(asyncio.all_tasks())
    try:
        with pytest.raises(
            ValueError,
            match={"config": "invalid literal", "application": "^app$", "server": "^server$"}[
                failure
            ],
        ):
            await task_worker.serve_worker(
                cast(Runtime, resources), cast(PgQueuer, worker), asyncio.Event()
            )
        pending = set(asyncio.all_tasks()) - before
        assert not pending, "worker task survived failed health server construction"
        assert worker.shutdown.is_set()
    finally:
        pending = set(asyncio.all_tasks()) - before
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
