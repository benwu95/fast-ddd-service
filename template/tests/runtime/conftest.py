import asyncio
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fast_ddd_adapter.infrastructure import create_engine, create_session_factory
from fast_ddd_adapter.migrations import add_kernel_versions
from fast_ddd_adapter.orm import Base
from fast_ddd_port.testing import TokenFactory
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from tests.runtime.support import JWT_SETTINGS

SERVICE_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logging"] = False
    add_kernel_versions(config)
    return config


@pytest.fixture(scope="session")
def postgres() -> Generator[PostgresContainer]:
    with PostgresContainer("postgres:18", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
async def database_url(postgres: PostgresContainer) -> str:
    url = postgres.get_connection_url()
    await asyncio.to_thread(command.upgrade, alembic_config(url), "heads")
    return url


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(database_url, application_name="runtime-tests", lock_timeout_ms=500)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    yield create_session_factory(engine)
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())


@pytest.fixture
def tokens() -> TokenFactory:
    return TokenFactory(JWT_SETTINGS)
