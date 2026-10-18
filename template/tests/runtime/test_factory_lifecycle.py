from types import ModuleType
from typing import Any, cast
from unittest.mock import Mock

import httpx2
import pytest
from fast_ddd_adapter.observability import Telemetry
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncEngine

from app import bootstrap, consumer, main
from tests.runtime.support import settings


@pytest.mark.parametrize("entrypoint", [main, consumer], ids=["api", "consumer"])
@pytest.mark.parametrize(
    "failure",
    [
        "settings",
        "engine",
        "session",
        "broker",
        "infrastructure",
        "resources",
        "events",
        "assembly",
    ],
)
async def test_factory_failure_does_not_start_telemetry_or_connect_resources(
    entrypoint: ModuleType, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = settings(rabbitmq_url=None) if failure == "settings" else settings()
    telemetry = Mock(spec=Telemetry)
    process = Mock(return_value=telemetry)
    monkeypatch.setattr(entrypoint, "configure_process", process)
    monkeypatch.setattr(entrypoint, "load_settings", Mock(return_value=configured))
    engines: list[AsyncEngine] = []
    brokers: list[RabbitBroker] = []
    clients: list[httpx2.AsyncClient] = []
    original_engine, original_broker = bootstrap.create_engine, bootstrap.create_broker
    original_http = main.create_http_client

    def engine(*args: Any, **kwargs: Any) -> AsyncEngine:
        if failure == "engine":
            raise ValueError("engine assembly failed")
        created = original_engine(*args, **kwargs)
        engines.append(created)
        return created

    def broker(*args: Any, **kwargs: Any) -> RabbitBroker:
        if failure == "broker":
            raise ValueError("factory assembly failed")
        created = original_broker(*args, **kwargs)
        brokers.append(created)
        return created

    def http(*args: Any, **kwargs: Any) -> httpx2.AsyncClient:
        created = original_http(*args, **kwargs)
        clients.append(created)
        return created

    monkeypatch.setattr(bootstrap, "create_engine", engine)
    monkeypatch.setattr(bootstrap, "create_broker", broker)

    def wire_resources(_settings: object) -> list[bootstrap.Closer]:
        client = http("extension", base_url="https://resource.test", timeout=5)
        return [client.aclose]

    monkeypatch.setattr(bootstrap, "wire_resources", wire_resources)
    monkeypatch.setattr(main, "create_http_client", http)
    if failure in {"session", "infrastructure"}:
        target = "create_session_factory" if failure == "session" else "configure"
        monkeypatch.setattr(bootstrap, target, Mock(side_effect=ValueError("assembly failed")))
    if failure in {"resources", "events"}:
        target = "wire_resources" if failure == "resources" else "wire_events"
        monkeypatch.setattr(bootstrap, target, Mock(side_effect=ValueError("assembly failed")))
    if failure == "assembly":
        target = "wire_http" if entrypoint is main else "wire_consumer"
        monkeypatch.setattr(entrypoint, target, Mock(side_effect=ValueError("assembly failed")))

    try:
        with pytest.raises(
            ValueError,
            match="RABBITMQ_URL is required" if failure == "settings" else "assembly failed",
        ):
            entrypoint.create_app()
        process.assert_not_called()
        telemetry.shutdown.assert_not_called()
        for created in engines:
            assert cast(Any, created.pool).checkedout() == 0
            assert cast(Any, created.pool).checkedin() == 0
        for created in brokers:
            assert not cast(Any, created)._connection
        for created in clients:
            assert cast(Any, created)._transport._inner._pool.connections == []
    finally:
        for created in clients:
            await created.aclose()
        for created in engines:
            await created.dispose()


@pytest.mark.parametrize("failure", ["jwks", "verifier"])
async def test_api_factory_failure_at_jwks_assembly_does_not_start_telemetry(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = settings()
    runtime = bootstrap.build_runtime(configured, role="api")
    process = Mock()
    clients: list[httpx2.AsyncClient] = []
    original = main.create_http_client

    def http(*args: Any, **kwargs: Any) -> httpx2.AsyncClient:
        if failure == "jwks":
            raise ValueError("JWKS client assembly failed")
        client = original(*args, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(main, "load_settings", Mock(return_value=configured))
    monkeypatch.setattr(main, "build_runtime", Mock(return_value=runtime))
    monkeypatch.setattr(main, "configure_process", process)
    monkeypatch.setattr(main, "create_http_client", http)
    if failure == "verifier":
        monkeypatch.setattr(main, "JwtVerifier", Mock(side_effect=ValueError("verifier")))
    try:
        with pytest.raises(ValueError, match=r"JWKS client assembly failed|verifier"):
            main.create_app()
        process.assert_not_called()
        assert cast(Any, runtime.engine.pool).checkedin() == 0
        assert cast(Any, runtime.engine.pool).checkedout() == 0
        assert not cast(Any, runtime.broker)._connection
        assert all(
            cast(Any, client)._transport._inner._pool.connections == [] for client in clients
        )
    finally:
        await runtime.close()
        for client in clients:
            await client.aclose()


@pytest.mark.parametrize("entrypoint", [main, consumer], ids=["api", "consumer"])
async def test_completed_factory_transfers_telemetry_to_runtime_once(
    entrypoint: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = settings()
    telemetry = Mock(spec=Telemetry)
    runtime = bootstrap.build_runtime(configured, role="test")
    monkeypatch.setattr(entrypoint, "configure_process", Mock(return_value=telemetry))
    monkeypatch.setattr(entrypoint, "load_settings", Mock(return_value=configured))
    monkeypatch.setattr(entrypoint, "build_runtime", Mock(return_value=runtime))
    app = entrypoint.create_app()
    assert app is not None
    telemetry.shutdown.assert_not_called()
    await runtime.close()
    telemetry.shutdown.assert_called_once()
