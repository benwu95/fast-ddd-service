import asyncio
from contextlib import nullcontext
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from app.bootstrap import Runtime
from tests.runtime.support import runtime


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
