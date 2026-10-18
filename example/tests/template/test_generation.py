import json
import sys
import tomllib
from pathlib import Path

import pytest
from copier import run_copy

from tests.template.support import PYTHON_VERSION, ROOT, run


@pytest.mark.parametrize("source", ["git", "path", "workspace"])
def test_generated_project_declares_its_kernel_source(
    template_repository: Path, tmp_path: Path, source: str
) -> None:
    run_copy(
        str(template_repository),
        tmp_path,
        defaults=True,
        vcs_ref="HEAD",
        data={"service_name": "orders-service", "kernel_source": source},
    )
    project = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert project["project"]["name"] == "orders-service"
    dependency = project["tool"]["uv"]["sources"]["fast-ddd-kernel"]
    if source == "git":
        assert dependency["tag"] == "v0.1.0"
        assert dependency["subdirectory"] == "kernel"
    elif source == "path":
        assert dependency == {"path": "../kernel"}
    else:
        assert dependency == {"workspace": True}
    assert not any("copier" in item for item in project["dependency-groups"]["dev"])


def test_generated_service_has_empty_typed_extension_points(
    template_repository: Path, tmp_path: Path
) -> None:
    run_copy(str(template_repository), tmp_path, defaults=True, vcs_ref="HEAD")
    result = run(
        tmp_path,
        sys.executable,
        "-c",
        """
import json
from unittest.mock import Mock
from fast_ddd.event_bus import EventBus
from fast_ddd_port.tasks import TaskRegistry
from fastapi import FastAPI
from app import wiring
from app.adapter.resources import Resources, configure_resources, resources
from app.settings import Settings
settings = Settings(service_name="empty", database_url="postgresql+asyncpg://localhost/test",
    jwt=dict(issuer="test", audience="test", jwks_url="http://localhost/jwks", user_id_claim="sub",
    organization_id_claim="org", permissions_claim="scope", permissions_format="list"))
assert wiring.wire_resources(settings) == []
assert wiring.wire_events(EventBus()) is None
app = FastAPI()
assert wiring.wire_http(app) is None
assert app.openapi()["paths"] == {}
assert wiring.wire_consumer(Mock(), Mock()) == []
registry = TaskRegistry()
assert wiring.wire_tasks(registry) is None
assert not registry.tasks and not registry.schedules
value = Resources()
configure_resources(value)
assert resources() is value
print(json.dumps({"fields": list(Settings.model_fields), "port": settings.worker_health_port}))
""",
    )
    settings = json.loads(result.stdout)
    assert "notification_url" not in settings["fields"]
    assert settings["port"] == 8081
    assert not (tmp_path / "app/core/billing").exists()
    assert not (tmp_path / "app/adapter/notification").exists()


def test_standalone_installation_has_own_lock_venv_and_kernel(generated_service: Path) -> None:
    service = generated_service
    assert (service / "uv.lock").is_file()
    assert not (service.parent / "kernel").exists()
    assert not (service / "tests/template").exists()
    assert {path.name for path in (service / "app/core").iterdir()} == {"__init__.py"}
    assert not any(
        path.name.startswith(".env") or path.suffix in {".pem", ".key", ".crt", ".p12"}
        for path in service.rglob("*")
        if ".venv" not in path.parts
    )
    result = run(
        service,
        str(service / ".venv/bin/python"),
        "-I",
        "-c",
        """
import json, sys
from importlib.metadata import distribution
from pathlib import Path
import fast_ddd, fast_ddd_adapter, fast_ddd_port, fast_ddd_devtools
kernel = distribution('fast-ddd-kernel')
direct = json.loads(kernel.read_text('direct_url.json'))
assert not direct.get('dir_info', {}).get('editable', False)
assert all(Path(module.__file__).is_relative_to(sys.prefix) for module in
    (fast_ddd, fast_ddd_adapter, fast_ddd_port, fast_ddd_devtools))
print(json.dumps({'prefix': sys.prefix, 'version': kernel.version, 'direct': direct,
                  'python': list(sys.version_info[:3])}))
""",
    )
    installed = json.loads(result.stdout)
    assert Path(installed["prefix"]) == service / ".venv"
    assert installed["version"] == "0.1.0"
    assert installed["python"] == [int(part) for part in PYTHON_VERSION.split(".")]
    project = tomllib.loads((service / "pyproject.toml").read_text())
    source = project["tool"]["uv"]["sources"]["fast-ddd-kernel"]
    if "git" in source:
        assert installed["direct"]["vcs_info"]["requested_revision"] == "v0.1.0"
    else:
        assert installed["direct"]["url"] == Path(source["path"]).as_uri()


@pytest.mark.parametrize("source", ["git", "path"])
def test_missing_kernel_source_fails_resolution(
    template_repository: Path, kernel_git_url: str, tmp_path: Path, source: str
) -> None:
    run_copy(
        str(template_repository),
        tmp_path,
        defaults=True,
        vcs_ref="HEAD",
        quiet=True,
        data={
            "kernel_source": source,
            "kernel_git_url": kernel_git_url,
            "kernel_version": "9.9.9",
            "kernel_path": "../missing-kernel",
        },
    )
    result = run(tmp_path, "uv", "lock", check=False)
    assert result.returncode != 0
    assert ("v9.9.9" if source == "git" else "missing-kernel") in result.stderr
    assert not (tmp_path / "uv.lock").exists()


def test_workspace_uses_framework_environment() -> None:
    result = run(
        ROOT / "example",
        sys.executable,
        "-c",
        "import sys; from importlib.metadata import version; "
        "print(sys.prefix); print(version('fast-ddd-kernel'))",
    )
    assert result.stdout.splitlines() == [str(ROOT / ".venv"), "0.1.0"]
