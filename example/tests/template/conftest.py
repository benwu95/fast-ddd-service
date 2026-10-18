import os
from collections.abc import Generator
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest
from copier import run_copy
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from tests.template.runtime_support import RuntimeInfrastructure
from tests.template.support import PYTHON_VERSION, ROOT, git, run, serve_git, snapshot_repository


@pytest.fixture(scope="session", autouse=True)
def disable_git_auto_maintenance() -> Generator[None]:
    # Copier's own git commits in temporary repositories otherwise spawn detached
    # maintenance that can write packs while copier deletes those directories.
    count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    config = {
        "GIT_CONFIG_COUNT": str(count + 2),
        f"GIT_CONFIG_KEY_{count}": "gc.auto",
        f"GIT_CONFIG_VALUE_{count}": "0",
        f"GIT_CONFIG_KEY_{count + 1}": "maintenance.auto",
        f"GIT_CONFIG_VALUE_{count + 1}": "false",
    }
    with patch.dict(os.environ, config):
        yield


@pytest.fixture(scope="session")
def template_repository(tmp_path_factory: pytest.TempPathFactory) -> Path:
    source = snapshot_repository(ROOT, tmp_path_factory.mktemp("template") / "source")
    git(source, "tag", "v0.1.0")
    return source


@pytest.fixture(scope="session")
def kernel_git_url(
    template_repository: Path, tmp_path_factory: pytest.TempPathFactory
) -> Generator[str]:
    with serve_git(template_repository, tmp_path_factory.mktemp("git-server") / "http") as url:
        yield url


@pytest.fixture(scope="session", params=["git", "path"])
def generated_service(
    request: pytest.FixtureRequest,
    template_repository: Path,
    kernel_git_url: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    service = tmp_path_factory.mktemp(f"standalone-{request.param}") / "orders"
    run_copy(
        str(template_repository),
        service,
        defaults=True,
        vcs_ref="HEAD",
        quiet=True,
        data={
            "service_name": "orders-service",
            "kernel_source": request.param,
            "kernel_git_url": kernel_git_url,
            "kernel_path": str(template_repository / "kernel"),
        },
    )
    run(service, "uv", "lock", "--python", PYTHON_VERSION)
    run(service, "uv", "sync", "--frozen", "--python", PYTHON_VERSION, timeout=240)
    return service


@pytest.fixture(scope="session")
def runtime_infrastructure() -> Generator[RuntimeInfrastructure]:
    with ExitStack() as stack:
        network = stack.enter_context(Network())
        postgres = stack.enter_context(
            PostgresContainer(
                "postgres:18", driver="asyncpg", username="smoke", password="smoke", dbname="smoke"
            )
            .with_network(network)
            .with_network_aliases("postgres")
        )
        rabbitmq = stack.enter_context(
            DockerContainer("rabbitmq:4-management")
            .with_network(network)
            .with_network_aliases("rabbitmq")
            .with_env("RABBITMQ_DEFAULT_USER", "smoke")
            .with_env("RABBITMQ_DEFAULT_PASS", "smoke")
            .with_env("RABBITMQ_DEFAULT_VHOST", "smoke")
            .with_exposed_ports(5672)
            .waiting_for(LogMessageWaitStrategy("Server startup complete"))
        )
        yield RuntimeInfrastructure(network, postgres, rabbitmq)
