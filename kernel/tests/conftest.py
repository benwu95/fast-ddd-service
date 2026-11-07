import asyncio
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from fast_ddd.context import User
from fast_ddd_adapter.infrastructure import create_engine, create_session_factory
from fast_ddd_adapter.migrations import add_kernel_versions
from fast_ddd_adapter.orm import Base
from tests import telemetry as test_telemetry

POSTGRES_IMAGE = "postgres:18"
RABBITMQ_IMAGE = "rabbitmq:4-management"


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", database_url)
    add_kernel_versions(config)
    return config


@pytest.fixture(scope="session", autouse=True)
def telemetry() -> test_telemetry.Telemetry:
    return test_telemetry.install()


@pytest.fixture(scope="session")
def postgres() -> Generator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def rabbitmq() -> Generator[DockerContainer]:
    container = (
        DockerContainer(RABBITMQ_IMAGE)
        .with_exposed_ports(5672)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def amqp_url(rabbitmq: DockerContainer) -> str:
    host = rabbitmq.get_container_host_ip()
    port = rabbitmq.get_exposed_port(5672)
    return f"amqp://guest:guest@{host}:{port}/"


@pytest.fixture(scope="session")
async def database_url(postgres: PostgresContainer) -> str:
    url = postgres.get_connection_url()
    await asyncio.to_thread(command.upgrade, alembic_config(url), "heads")
    return url


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(database_url, application_name="kernel-tests", lock_timeout_ms=500)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    yield create_session_factory(engine)
    async with engine.begin() as connection:
        names = [t.name for t in reversed(Base.metadata.sorted_tables)]
        names += ["pgqueuer", "pgqueuer_log", "pgqueuer_schedules", "pgqueuer_statistics"]
        tables = ", ".join(f'"{name}"' for name in names)
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def organization_id() -> UUID:
    return uuid4()


@pytest.fixture
def doer() -> User:
    return User(id="tester", name="Tester")
