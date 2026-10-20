import asyncio
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fast_ddd.event_bus import EventBus
from fast_ddd_adapter.http_client import create_http_client
from fast_ddd_adapter.infrastructure import configure, create_engine, create_session_factory
from fast_ddd_adapter.migrations import add_kernel_versions
from fast_ddd_adapter.tasks import PgQueuerTaskQueue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from app.adapter.notification.notification_client import NotificationClient
from app.adapter.resources import Resources, configure_resources
from app.wiring import wire_events
from tests.support import NOTIFICATION_URL, NotificationService, RecordingPublisher

POSTGRES_IMAGE = "postgres:18"
EXAMPLE_ROOT = Path(__file__).parent.parent
TABLES = (
    "billing_invoice_line",
    "billing_invoice",
    "domain_event",
    "processed_message",
    "pgqueuer",
    "pgqueuer_log",
    "pgqueuer_schedules",
    "pgqueuer_statistics",
)


@pytest.fixture(autouse=True)
def reference_service_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATION_URL", NOTIFICATION_URL)


def alembic_config(database_url: str) -> Config:
    config = Config(str(EXAMPLE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logging"] = False
    add_kernel_versions(config)
    return config


@pytest.fixture(scope="session")
def postgres() -> Generator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
async def database_url(postgres: PostgresContainer) -> str:
    """The test database is built by the migrations, so they are tested on every run."""
    url = postgres.get_connection_url()
    await asyncio.to_thread(command.upgrade, alembic_config(url), "heads")
    return url


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(database_url, application_name="example-tests", lock_timeout_ms=500)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    yield create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))


@dataclass
class Infrastructure:
    publisher: RecordingPublisher
    notifications: NotificationService


@pytest.fixture
async def infrastructure(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[Infrastructure]:
    """The kernel and service wiring of ``build_runtime``, with fakes at the process edge."""
    publisher = RecordingPublisher()
    notifications = NotificationService()
    bus = EventBus()
    wire_events(bus)
    configure(
        session_factory=session_factory,
        event_bus=bus,
        publisher=publisher,
        task_queue=PgQueuerTaskQueue(),
    )
    http = create_http_client(
        "notification",
        base_url=NOTIFICATION_URL,
        timeout=1.0,
        retry_delay=0,
        transport=httpx2.MockTransport(notifications.handle),
    )
    configure_resources(Resources(notification=NotificationClient(http)))
    yield Infrastructure(publisher, notifications)
    await http.aclose()


@pytest.fixture
def organization_id() -> UUID:
    return uuid4()
