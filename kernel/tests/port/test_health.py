import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx2
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from fast_ddd_port.http import health_router


async def test_health_reports_role_failure_and_bounds_database_probe() -> None:
    engine = MagicMock()
    connection = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = connection
    alive = True
    app = FastAPI()
    app.include_router(
        health_router(cast(AsyncEngine, engine), is_alive=lambda: alive, timeout_seconds=0.01)
    )
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 200
        connection.execute.assert_awaited_once()

        connection.execute.side_effect = ConnectionError("database secret")
        unavailable = await client.get("/health/ready")
        assert unavailable.status_code == 503
        assert "database secret" not in unavailable.text
        assert (await client.get("/health/live")).status_code == 200

        async def stalled(*_: object) -> None:
            await asyncio.sleep(60)

        connection.execute.side_effect = stalled
        async with asyncio.timeout(1):
            response = await client.get("/health/ready")
        assert response.status_code == 503
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["code"] == "server.unavailable"
        engine.connect.return_value.__aexit__.assert_awaited()
        alive = False
        connection.execute.reset_mock()
        assert (await client.get("/health/live")).status_code == 503
        assert (await client.get("/health/ready")).status_code == 503
        connection.execute.assert_not_awaited()
