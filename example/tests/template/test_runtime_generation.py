import sys
from pathlib import Path

from copier import run_copy

from tests.template.support import run

FACTORY_CHECK = """
import os
import json
from unittest.mock import patch
os.environ.update(SERVICE_NAME="empty", DATABASE_URL="postgresql+asyncpg://localhost/test",
    RABBITMQ_URL="amqp://guest:guest@localhost/", JWT=json.dumps(dict(
    issuer="test", audience="test", jwks_url="http://localhost/jwks", user_id_claim="sub",
    organization_id_claim="org", permissions_claim="scope", permissions_format="list")))
from app import bootstrap, main, consumer
from app.settings import Settings
settings = Settings()
with patch.object(bootstrap, "wire_resources", side_effect=RuntimeError("assembly")):
    for module in (main, consumer):
        with patch.object(module, "configure_process") as telemetry:
            try:
                module.create_app()
            except RuntimeError as error:
                assert str(error) == "assembly"
            else:
                raise AssertionError("assembly failure was swallowed")
            telemetry.assert_not_called()
app = main.create_app()
assert app.openapi()["paths"] == {}
assert consumer.create_app() is not None
"""


def test_generated_factories_preserve_synchronous_assembly_ownership(
    template_repository: Path, tmp_path: Path
) -> None:
    run_copy(str(template_repository), tmp_path, defaults=True, vcs_ref="HEAD")
    run(tmp_path, sys.executable, "-c", FACTORY_CHECK)


def test_generated_worker_exposes_the_plain_dsn_and_empty_registry(
    template_repository: Path, tmp_path: Path
) -> None:
    run_copy(str(template_repository), tmp_path, defaults=True, vcs_ref="HEAD")
    run(
        tmp_path,
        sys.executable,
        "-c",
        """
from unittest.mock import Mock, patch
from app import task_worker
assert task_worker.driver_dsn("postgresql+asyncpg://user:password@localhost/test") == "postgresql://user:password@localhost/test"
with patch.object(task_worker, "build_worker") as build:
    runtime = Mock()
    connection = Mock()
    assert task_worker.build_task_worker(runtime, connection) is build.return_value
    registry = build.call_args.args[1]
    assert not registry.tasks and not registry.schedules
""",
    )
