import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.task_worker import driver_dsn
from tests.runtime.support import JWT_SETTINGS

EXAMPLE_ROOT = Path(__file__).resolve().parents[2]


def environment() -> dict[str, str]:
    return {
        **os.environ,
        "SERVICE_NAME": "example",
        "DATABASE_URL": "postgresql+asyncpg://user:secret@db.invalid:5432/example",
        "RABBITMQ_URL": "amqp://guest:guest@rabbitmq.invalid:5672/",
        **{
            f"JWT__{key.upper()}": str(value)
            for key, value in JWT_SETTINGS.model_dump(exclude_defaults=True).items()
        },
    }


@pytest.mark.parametrize(
    "factory", ["app.main:create_app", "app.consumer:create_app"], ids=["api", "consumer"]
)
def test_factories_build_from_the_environment(factory: str) -> None:
    module, name = factory.split(":")
    result = subprocess.run(
        [sys.executable, "-c", f"from {module} import {name}; print(type({name}()).__name__)"],
        cwd=EXAMPLE_ROOT,
        env=environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith(("FastAPI", "AsgiFastStream"))


def test_task_worker_uses_a_plain_asyncpg_dsn() -> None:
    url = "postgresql+asyncpg://user:p%40ss@db:5432/example"
    assert driver_dsn(url) == "postgresql://user:p%40ss@db:5432/example"


def test_consumer_cli_reapplies_logging_before_broker_startup_failure() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import asyncio
from unittest.mock import AsyncMock
import uvicorn
from uvicorn.lifespan.on import LifespanOn
from faststream._internal.cli.dto import RunArgs
from faststream._internal.cli.main import _run


async def serve(server):
    server.config.load()
    consumer = server.config.app
    broker = consumer.brokers[0]
    failed = asyncio.Event()
    async def fail():
        failed.set()
        raise ValueError('STARTUP_PRIVATE_PASSWORD')
    broker.start = AsyncMock(side_effect=fail)
    lifespan = LifespanOn(server.config)
    await lifespan.startup()
    await failed.wait()
    await lifespan.shutdown()
    assert lifespan.startup_failed or lifespan.shutdown_failed

uvicorn.Server.serve = serve
_run(RunArgs(app='app.consumer:create_app', is_factory=True))
""",
        ],
        cwd=EXAMPLE_ROOT,
        env=environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "STARTUP_PRIVATE_PASSWORD" not in output
    records = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    assert any(record["level"] == "ERROR" for record in records)
    assert any("ValueError" in record.get("exception", "") for record in records)
