from collections.abc import AsyncGenerator

import asyncpg
import httpx2
import pytest
from fast_ddd_adapter.messaging import create_broker
from fast_ddd_port.testing import TokenFactory
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.bootstrap import Runtime
from app.main import build_app
from app.settings import Settings
from app.task_worker import driver_dsn
from tests.conftest import Infrastructure
from tests.support import FRONTEND, JWT_SETTINGS, NOTIFICATION_URL


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory(JWT_SETTINGS)


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        service_name="example-tests",
        database_url=database_url,
        rabbitmq_url="amqp://guest:guest@rabbitmq.invalid:5672/",
        jwt=JWT_SETTINGS,
        cors_allow_origins=[FRONTEND],
        notification_url=NOTIFICATION_URL,
    )


@pytest.fixture
async def client(
    settings: Settings,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    infrastructure: Infrastructure,
    tokens: TokenFactory,
) -> AsyncGenerator[httpx2.AsyncClient]:
    """The real app from ``build_app``; the ASGI transport does not run its lifespan."""
    del infrastructure
    runtime = Runtime(settings, engine, session_factory, create_broker(settings.rabbitmq_url or ""))
    app = build_app(runtime, tokens.verifier())
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def connection(database_url: str) -> AsyncGenerator[asyncpg.Connection]:
    connection = await asyncpg.connect(driver_dsn(database_url))
    yield connection
    await connection.close()
