import asyncio
import json
import os
import signal
import socket
import subprocess
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.error import URLError
from urllib.request import urlopen

import asyncpg
from pgqueuer import AsyncpgDriver
from pgqueuer.queries import Queries
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from tests.template.support import isolated_environment, run

type Role = Literal["api", "consumer", "worker"]
ROLES: tuple[Role, ...] = ("api", "consumer", "worker")


class RunningService(Protocol):
    def poll(self) -> int | None: ...


@dataclass(frozen=True)
class RuntimeSnapshot:
    status: str
    attempts: int
    jobs: int
    logs: int
    schedules: int
    successes: int
    connections: int


@dataclass(frozen=True)
class RuntimeInfrastructure:
    network: Network
    postgres: PostgresContainer
    rabbitmq: DockerContainer

    @property
    def database_url(self) -> str:
        return self.postgres.get_connection_url()

    @property
    def amqp_url(self) -> str:
        host = self.rabbitmq.get_container_host_ip()
        port = self.rabbitmq.get_exposed_port(5672)
        return f"amqp://smoke:smoke@{host}:{port}/smoke"

    def rabbit_state(self, resource: str, *fields: str) -> list[dict[str, object]]:
        result = self.rabbitmq.exec(
            ["rabbitmqctl", "--quiet", f"list_{resource}", "--formatter", "json", *fields]
        )
        assert result.exit_code == 0, result.output.decode()
        return cast(list[dict[str, object]], json.loads(result.output))

    def consumers(self) -> list[dict[str, object]]:
        return self.rabbit_state("consumers", "-p", "smoke")

    def queues(self) -> list[dict[str, object]]:
        return self.rabbit_state("queues", "-p", "smoke", "name")

    def connections(self) -> list[dict[str, object]]:
        return self.rabbit_state("connections", "name")

    def snapshot(self, sentinel: int) -> RuntimeSnapshot:
        async def inspect() -> RuntimeSnapshot:
            connection = await asyncpg.connect(
                self.postgres.get_connection_url(driver=None), timeout=5
            )
            try:
                row = await connection.fetchrow(
                    "SELECT status::text AS status, attempts FROM pgqueuer WHERE id=$1", sentinel
                )
                assert row is not None
                counts = await connection.fetchrow(
                    """SELECT
                    (SELECT count(*) FROM pgqueuer) AS jobs,
                    (SELECT count(*) FROM pgqueuer_log) AS logs,
                    (SELECT count(*) FROM pgqueuer_schedules) AS schedules,
                    (SELECT count(*) FROM pgqueuer_statistics
                     WHERE status='successful' AND count>0) AS successes,
                    (SELECT count(*) FROM pg_stat_activity
                     WHERE datname=current_database() AND pid<>pg_backend_pid()) AS connections
                    """
                )
                assert counts is not None
                return RuntimeSnapshot(
                    cast(str, row["status"]),
                    cast(int, row["attempts"]),
                    *(
                        cast(int, counts[name])
                        for name in ("jobs", "logs", "schedules", "successes", "connections")
                    ),
                )
            finally:
                await connection.close()

        return asyncio.run(inspect())


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return cast(tuple[str, int], listener.getsockname())[1]


def runtime_environment(
    infrastructure: RuntimeInfrastructure, port: int, **overrides: str
) -> dict[str, str]:
    environment = isolated_environment()
    for key in list(environment):
        if key.startswith("JWT__"):
            environment.pop(key)
    environment.update(
        SERVICE_NAME="template-runtime-smoke",
        DATABASE_URL=infrastructure.database_url,
        RABBITMQ_URL=infrastructure.amqp_url,
        JWT=json.dumps(
            {
                "issuer": "smoke",
                "audience": "smoke",
                "jwks_url": "http://127.0.0.1:1/jwks",
                "user_id_claim": "sub",
                "organization_id_claim": "organization_id",
                "permissions_claim": "permissions",
                "permissions_format": "list",
            }
        ),
        TELEMETRY_EXPORTER="none",
        WORKER_HEALTH_HOST="127.0.0.1",
        WORKER_HEALTH_PORT=str(port),
        WORKER_SHUTDOWN_TIMEOUT_SECONDS="5",
    )
    environment.update(overrides)
    return environment


def role_command(
    service: Path, role: Role, port: int, *, host: str = "127.0.0.1"
) -> tuple[str, ...]:
    python = str(service / ".venv/bin/python")
    match role:
        case "api":
            return (
                python,
                "-m",
                "uvicorn",
                "--factory",
                "app.main:create_app",
                "--host",
                host,
                "--port",
                str(port),
            )
        case "consumer":
            return (
                str(service / ".venv/bin/faststream"),
                "run",
                "--factory",
                "app.consumer:create_app",
                "--host",
                host,
                "--port",
                str(port),
            )
        case "worker":
            return (python, "-m", "app.task_worker")


@contextmanager
def service_process(
    service: Path, command: Sequence[str], environment: dict[str, str], log_path: Path
) -> Generator[subprocess.Popen[str]]:
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=service,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            yield process
        finally:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def wait_health(
    port: int, role: Role, process: RunningService, log: Path, *, timeout: float = 20
) -> None:
    deadline = time.monotonic() + timeout
    paths = ("live",) if role == "consumer" else ("live", "ready")
    consecutive = 0
    while time.monotonic() < deadline:
        assert process.poll() is None, log.read_text()
        try:
            for path in paths:
                with urlopen(f"http://127.0.0.1:{port}/health/{path}", timeout=0.3) as response:
                    assert response.status == (204 if role == "consumer" else 200)
            consecutive += 1
            if consecutive == 3:
                if role == "api":
                    with urlopen(f"http://127.0.0.1:{port}/openapi.json", timeout=1) as response:
                        assert json.load(response)["paths"] == {}
                return
        except (URLError, TimeoutError, ConnectionError):
            consecutive = 0
        time.sleep(0.1)
    raise TimeoutError(f"health deadline expired for {role}: {log.read_text()}")


def assert_port_closed(port: int) -> None:
    with socket.socket() as connection:
        connection.settimeout(1)
        assert connection.connect_ex(("127.0.0.1", port)) != 0


def assert_process_group_closed(pid: int) -> None:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return
    raise AssertionError(f"process group {pid} survived cleanup")


def assert_empty_wiring(service: Path, environment: dict[str, str]) -> None:
    run(
        service,
        str(service / ".venv/bin/python"),
        "-c",
        """
import asyncio
from fast_ddd_port.tasks import TaskRegistry
from app.bootstrap import build_runtime
from app.settings import Settings
from app.wiring import wire_consumer, wire_tasks
runtime = build_runtime(Settings(), role="smoke")
try:
    assert wire_consumer(runtime.broker, runtime.session_factory) == []
    assert not runtime.broker.subscribers
    registry = TaskRegistry()
    wire_tasks(registry)
    assert not registry.tasks and not registry.schedules
finally:
    asyncio.run(runtime.close())
""",
        environment=environment,
    )


def prepare_runtime_database(
    service: Path, infrastructure: RuntimeInfrastructure, environment: dict[str, str]
) -> int:
    run(
        service,
        str(service / ".venv/bin/fast-ddd-alembic"),
        "upgrade",
        "heads",
        environment=environment,
    )

    async def seed() -> int:
        connection = await asyncpg.connect(infrastructure.postgres.get_connection_url(driver=None))
        try:
            await connection.execute(
                "TRUNCATE pgqueuer, pgqueuer_log, pgqueuer_schedules, pgqueuer_statistics"
            )
            ids = await Queries(AsyncpgDriver(connection)).enqueue("unregistered-smoke", b"{}")
            assert ids[0] is not None
            return int(ids[0])
        finally:
            await connection.close()

    sentinel = asyncio.run(seed())
    assert_runtime_clean(infrastructure, sentinel)
    return sentinel


def assert_runtime_clean(infrastructure: RuntimeInfrastructure, sentinel: int) -> None:
    deadline = time.monotonic() + 10
    while True:
        snapshot = infrastructure.snapshot(sentinel)
        connections = infrastructure.connections()
        if snapshot.connections == 0 and not connections:
            assert snapshot == RuntimeSnapshot("queued", 0, 1, 1, 0, 0, 0), snapshot
            assert infrastructure.consumers() == []
            queues = infrastructure.queues()
            assert queues == [], queues
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"runtime resources survived shutdown: {snapshot}, MQ={connections}"
            )
        time.sleep(0.1)
