import json
import shutil
import sys
import tomllib
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from copier import run_copy

from tests.template.runtime_support import (
    ROLES,
    Role,
    RuntimeInfrastructure,
    assert_port_closed,
    assert_runtime_clean,
    prepare_runtime_database,
    role_command,
    runtime_environment,
    wait_health,
)
from tests.template.support import PYTHON_VERSION, git, run


def test_kernel_git_origin_is_reachable_outside_the_host_loopback(kernel_git_url: str) -> None:
    assert urlsplit(kernel_git_url).hostname == "host.docker.internal"


def test_generated_container_instructions_have_the_required_build_context(
    template_repository: Path, tmp_path: Path
) -> None:
    run_copy(str(template_repository), tmp_path, defaults=True, vcs_ref="HEAD")
    assert (tmp_path / "Dockerfile").is_file()
    assert (tmp_path / ".dockerignore").is_file()
    assert not (tmp_path / "uv.lock").exists()
    result = run(tmp_path, "docker", "build", "--check", ".")
    assert result.returncode == 0


@pytest.fixture(scope="module")
def service_image(
    generated_service: Path,
    kernel_git_url: str,
    template_repository: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[str]:
    context = tmp_path_factory.mktemp("linux-image") / "service"
    shutil.copytree(
        generated_service, context, ignore=shutil.ignore_patterns(".venv", "__pycache__")
    )
    project = tomllib.loads((context / "pyproject.toml").read_text())
    assert project["tool"]["uv"]["sources"]["fast-ddd-kernel"]["git"] == kernel_git_url
    locked = tomllib.loads((context / "uv.lock").read_text())
    (kernel,) = [package for package in locked["package"] if package["name"] == "fast-ddd-kernel"]
    assert kernel["source"]["git"].split("?")[0] == kernel_git_url
    for name in (
        "app/.env.local",
        "app/private.key",
        "alembic/certificate.pem",
        "app/certificate.crt",
        "app/certificate.cer",
        "app/certificate.p12",
        "app/certificate.pfx",
        ".venv/host-only-marker",
        "kernel/host-only-marker",
    ):
        path = context / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("fixture-only content\n")
    image = f"fast-ddd-template-test:{uuid4().hex}"
    try:
        network = (
            ("--network", "host", "--add-host", "host.docker.internal:127.0.0.1")
            if sys.platform.startswith("linux")
            else ()
        )
        built = run(
            context,
            "docker",
            "build",
            "--no-cache",
            *network,
            "--tag",
            image,
            ".",
            check=False,
            timeout=600,
        )
        assert built.returncode == 0, built.stdout + built.stderr
        installed = run(
            context,
            "docker",
            "run",
            "--rm",
            image,
            "python",
            "-c",
            """
import json, sys
from importlib.metadata import distribution
from importlib.resources import files
from pathlib import Path
kernel = distribution('fast-ddd-kernel')
direct = json.loads(kernel.read_text('direct_url.json'))
assert not direct.get('dir_info', {}).get('editable', False)
for package in ('fast_ddd', 'fast_ddd_adapter', 'fast_ddd_port', 'fast_ddd_devtools'):
    assert str(files(package)).startswith('/service/.venv/')
    assert files(package).joinpath('py.typed').is_file()
assert files('fast_ddd_adapter').joinpath('migrations/versions/fastddd_0003_pgqueuer.py').is_file()
assert not Path('/service/kernel').exists()
assert not Path('/service/.venv/host-only-marker').exists()
secret_suffixes = {'.key', '.pem', '.crt', '.cer', '.p12', '.pfx'}
assert not any(path.name.startswith('.env') or path.suffix in secret_suffixes
               for base in ('app', 'alembic') for path in Path(base).rglob('*'))
print(json.dumps({'python': list(sys.version_info[:3]),
                  'version': kernel.version, 'direct': direct}))
""",
        )
        result = json.loads(installed.stdout)
        assert result["python"] == [int(part) for part in PYTHON_VERSION.split(".")]
        assert result["version"] == "0.1.0"
        assert result["direct"]["url"] == kernel_git_url
        assert result["direct"]["vcs_info"]["commit_id"] == git(
            template_repository, "rev-parse", "v0.1.0"
        )
        yield image
    finally:
        run(context, "docker", "image", "rm", "--force", image, check=False)


@dataclass
class ContainerService:
    directory: Path
    identifier: str
    log: Path

    def poll(self) -> int | None:
        state = json.loads(
            run(
                self.directory, "docker", "inspect", "--format", "{{json .State}}", self.identifier
            ).stdout
        )
        logs = run(self.directory, "docker", "logs", self.identifier, check=False)
        self.log.write_text(logs.stdout + logs.stderr)
        return None if state["Running"] else cast(int, state["ExitCode"])


@pytest.mark.parametrize("generated_service", ["git"], indirect=True)
@pytest.mark.parametrize("role", ROLES)
def test_linux_image_runs_and_stops_each_service_role(
    generated_service: Path,
    service_image: str,
    runtime_infrastructure: RuntimeInfrastructure,
    tmp_path: Path,
    role: Role,
) -> None:
    infrastructure = runtime_infrastructure
    host_environment = runtime_environment(infrastructure, 8080)
    sentinel = prepare_runtime_database(generated_service, infrastructure, host_environment)
    environment = runtime_environment(
        infrastructure,
        8080,
        DATABASE_URL="postgresql+asyncpg://smoke:smoke@postgres:5432/smoke",
        RABBITMQ_URL="amqp://smoke:smoke@rabbitmq:5672/smoke",
        WORKER_HEALTH_HOST="0.0.0.0",
    )
    names = (
        "SERVICE_NAME",
        "DATABASE_URL",
        "RABBITMQ_URL",
        "JWT",
        "TELEMETRY_EXPORTER",
        "WORKER_HEALTH_HOST",
        "WORKER_HEALTH_PORT",
        "WORKER_SHUTDOWN_TIMEOUT_SECONDS",
    )
    options = [argument for name in names for argument in ("--env", f"{name}={environment[name]}")]
    identifier = run(
        generated_service,
        "docker",
        "create",
        "--network",
        infrastructure.network.name,
        "--publish",
        "127.0.0.1::8080",
        *options,
        service_image,
        *role_command(Path("/service"), role, 8080, host="0.0.0.0"),
    ).stdout.strip()
    try:
        assert (
            json.loads(
                run(
                    generated_service,
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .Mounts}}",
                    identifier,
                ).stdout
            )
            == []
        )
        run(generated_service, "docker", "start", identifier)
        published = run(generated_service, "docker", "port", identifier, "8080/tcp").stdout
        port = int(published.strip().rsplit(":", 1)[1])
        process = ContainerService(generated_service, identifier, tmp_path / f"{role}.log")
        wait_health(port, role, process, process.log, timeout=30)
        assert infrastructure.consumers() == []
        assert infrastructure.queues() == []
        run(generated_service, "docker", "stop", "--timeout", "10", identifier, timeout=15)
        state = json.loads(
            run(
                generated_service, "docker", "inspect", "--format", "{{json .State}}", identifier
            ).stdout
        )
        assert state["Status"] == "exited"
        assert state["ExitCode"] in ({0} if role == "worker" else {0, 143})
        assert state["OOMKilled"] is False
        assert_port_closed(port)
        assert_runtime_clean(infrastructure, sentinel)
    finally:
        run(generated_service, "docker", "rm", "--force", identifier, check=False)
