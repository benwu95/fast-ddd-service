import asyncio
from contextlib import nullcontext
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
import uvicorn
from fast_ddd_adapter.observability import Telemetry
from pgqueuer import PgQueuer

from app import task_worker
from app.bootstrap import Runtime
from app.settings import Settings
from tests.support import JWT_SETTINGS


def settings(**values: object) -> Settings:
    return Settings.model_validate(
        {
            "service_name": "worker-test",
            "database_url": "postgresql+asyncpg://u:p@localhost/test",
            "rabbitmq_url": "amqp://guest:guest@localhost/",
            "notification_url": "https://notice.test",
            "jwt": JWT_SETTINGS,
            **values,
        }
    )


def runtime() -> Mock:
    result = Mock(spec=Runtime)
    result.settings = settings(worker_shutdown_timeout_seconds=0.05)
    result.close = AsyncMock()
    result.broker = Mock()
    result.broker.connect = AsyncMock()
    result.broker.stop = AsyncMock()
    return result


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
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://worker.test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            assert (await client.get("/health/ready")).status_code == 200
            assert (await client.get("/invoices")).status_code == 404
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


async def test_api_start_failure_closes_broker_and_runtime() -> None:
    from fast_ddd_port.auth import JwtVerifier

    from app.main import build_app

    resources = runtime()
    resources.broker.connect.side_effect = OSError("API broker down")
    app = build_app(cast(Runtime, resources), cast(JwtVerifier, Mock()))
    with pytest.raises(OSError, match="API broker down"):
        async with app.router.lifespan_context(app):
            pytest.fail("startup should fail")
    resources.broker.stop.assert_awaited_once()
    resources.close.assert_awaited_once()


async def test_consumer_start_failure_closes_broker_and_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fast_ddd_adapter.messaging import create_broker

    from app.consumer import build_consumer

    resources = runtime()
    resources.broker = create_broker("amqp://guest:guest@localhost/")
    start, stop = AsyncMock(side_effect=OSError("consumer broker down")), AsyncMock()
    monkeypatch.setattr(resources.broker, "start", start)
    monkeypatch.setattr(resources.broker, "stop", stop)
    app = build_consumer(cast(Runtime, resources))
    with pytest.raises(OSError, match="consumer broker down"):
        async with app.start_lifespan_context():
            await asyncio.sleep(0.01)
    stop.assert_awaited_once()
    resources.close.assert_awaited_once()


async def test_api_shutdown_error_still_closes_runtime() -> None:
    from fast_ddd_port.auth import JwtVerifier

    from app.main import build_app

    resources = runtime()
    resources.broker.stop.side_effect = OSError("broker close failed")
    app = build_app(cast(Runtime, resources), cast(JwtVerifier, Mock()))
    with pytest.raises(OSError, match="broker close failed"):
        async with app.router.lifespan_context(app):
            pass
    resources.close.assert_awaited_once()


@pytest.mark.parametrize("close_fails", [False, True])
async def test_consumer_broker_shutdown_always_closes_runtime_once(
    monkeypatch: pytest.MonkeyPatch, close_fails: bool
) -> None:
    from fast_ddd_adapter.messaging import create_broker

    from app.consumer import build_consumer

    resources = runtime()
    resources.broker = create_broker("amqp://guest:guest@localhost/")
    monkeypatch.setattr(resources.broker, "start", AsyncMock())
    monkeypatch.setattr(resources.broker, "declare_exchange", AsyncMock())
    monkeypatch.setattr(resources.broker, "declare_queue", AsyncMock())
    connection = AsyncMock()
    if close_fails:
        connection.close.side_effect = OSError("broker close failed")
    monkeypatch.setattr(resources.broker, "_connection", connection)
    app = build_consumer(cast(Runtime, resources))
    with pytest.raises(OSError, match="broker close failed") if close_fails else nullcontext():
        async with app.start_lifespan_context():
            await asyncio.sleep(0)
    connection.close.assert_awaited_once()
    resources.close.assert_awaited_once()


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
