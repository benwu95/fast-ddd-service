import json
import shutil
import sys
from pathlib import Path

import pytest
from copier import run_copy, run_recopy
from testcontainers.community.postgres import PostgresContainer

from tests.template.support import PYTHON_VERSION, ROOT, git, isolated_environment, run


@pytest.mark.parametrize("initialize", [True, False])
def test_service_baseline_is_a_separate_optional_branch(
    template_repository: Path, tmp_path: Path, initialize: bool
) -> None:
    run_copy(
        str(template_repository),
        tmp_path,
        defaults=True,
        vcs_ref="HEAD",
        data={"initialize_service_baseline": initialize},
    )
    result = run(
        tmp_path,
        sys.executable,
        "-c",
        """
import json
from alembic.config import Config
from alembic.script import ScriptDirectory
from fast_ddd_adapter.migrations import add_kernel_versions
config = Config("alembic.ini")
add_kernel_versions(config)
script = ScriptDirectory.from_config(config)
heads = {head: sorted(script.get_revision(head).branch_labels) for head in script.get_heads()}
print(json.dumps(heads))
""",
    )
    heads = json.loads(result.stdout)
    assert len(heads) == (2 if initialize else 1)
    assert "fast_ddd" in {label for labels in heads.values() for label in labels}
    if initialize:
        assert heads["service_0000"] == ["service"]
    else:
        assert "service_0000" not in heads


def test_first_business_revision_uses_service_branch_and_round_trips(
    generated_service: Path, tmp_path: Path
) -> None:
    service = tmp_path / "migration-service"
    shutil.copytree(
        generated_service, service, ignore=shutil.ignore_patterns(".venv", "__pycache__")
    )
    run(service, "uv", "sync", "--frozen", "--python", PYTHON_VERSION)
    with PostgresContainer("postgres:18", driver="asyncpg") as postgres:
        environment = isolated_environment(DATABASE_URL=postgres.get_connection_url())
        run(
            service,
            "uv",
            "run",
            "--frozen",
            "fast-ddd-alembic",
            "upgrade",
            "heads",
            environment=environment,
        )
        (service / "app/adapter/repository/models.py").write_text(
            "from fast_ddd_adapter.orm import Base\n"
            "from sqlalchemy import Column, Integer, Table\n"
            "orders = Table('order_record', Base.metadata,\n"
            "    Column('id', Integer, primary_key=True))\n"
        )
        run(service, "make", "migration", "name=create order record", environment=environment)
        revisions = list((service / "alembic/versions").glob("*.py"))
        assert len(revisions) == 2
        (created,) = [path for path in revisions if path.name != "0000_service.py"]
        assert "service_0000" in created.read_text()
        run(
            service,
            "uv",
            "run",
            "--frozen",
            "fast-ddd-alembic",
            "upgrade",
            "heads",
            environment=environment,
        )
        run(service, "uv", "run", "--frozen", "fast-ddd-alembic", "check", environment=environment)
        check_schema = """
import asyncio, os, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
async def check():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    async with engine.connect() as connection:
        exists = await connection.scalar(text("SELECT to_regclass('order_record') IS NOT NULL"))
        assert exists == (sys.argv[1] == 'present')
        assert await connection.scalar(text('SELECT count(*) FROM alembic_version')) == 2
    await engine.dispose()
asyncio.run(check())
"""
        python = str(service / ".venv/bin/python")
        run(service, python, "-c", check_schema, "present", environment=environment)
        run(
            service,
            "uv",
            "run",
            "--frozen",
            "fast-ddd-alembic",
            "downgrade",
            "service_0000",
            environment=environment,
        )
        run(service, python, "-c", check_schema, "absent", environment=environment)
        run(
            service,
            "uv",
            "run",
            "--frozen",
            "fast-ddd-alembic",
            "upgrade",
            "heads",
            environment=environment,
        )
        run(service, python, "-c", check_schema, "present", environment=environment)
        run(service, "uv", "run", "--frozen", "fast-ddd-alembic", "check", environment=environment)


def test_example_keeps_original_migration_chain() -> None:
    directory = ROOT / "example/alembic/versions"
    names = git(ROOT, "ls-tree", "--name-only", "HEAD", "example/alembic/versions/").splitlines()
    assert names
    for name in names:
        original = run(ROOT, "git", "show", f"HEAD:{name}").stdout.encode()
        assert (ROOT / name).read_bytes() == original
    assert not (directory / "0000_service.py").exists()


@pytest.mark.parametrize("initialize", [True, False])
@pytest.mark.parametrize("source", ["git", "path"])
def test_source_switch_and_deleted_initialization_keep_one_service_root(
    template_repository: Path, tmp_path: Path, initialize: bool, source: str
) -> None:
    run_copy(
        str(template_repository),
        tmp_path,
        defaults=True,
        vcs_ref="HEAD",
        quiet=True,
        data={"kernel_source": "workspace", "initialize_service_baseline": initialize},
    )
    versions = tmp_path / "alembic/versions"
    versions.mkdir(exist_ok=True)
    if initialize:
        (versions / "0000_service.py").unlink()
        parent = "service_0000"
    else:
        (original,) = (ROOT / "example/alembic/versions").glob("*.py")
        shutil.copyfile(original, versions / original.name)
        parent = "3f6a1c2d9b10"
    later = versions / "later.py"
    later.write_text(
        f"revision = 'later'\ndown_revision = '{parent}'\n"
        "branch_labels = None\ndepends_on = None\n"
        "def upgrade(): pass\ndef downgrade(): pass\n"
    )
    before = later.read_bytes()
    (tmp_path / "app/settings.py").unlink()
    run_recopy(
        tmp_path,
        defaults=True,
        overwrite=True,
        vcs_ref="HEAD",
        quiet=True,
        data={"kernel_source": source},
    )
    assert later.read_bytes() == before
    assert (tmp_path / "app/settings.py").is_file()
    assert (versions / "0000_service.py").exists() is initialize
    result = run(
        tmp_path,
        sys.executable,
        "-c",
        """
from alembic.config import Config
from alembic.script import ScriptDirectory
from fast_ddd_adapter.migrations import add_kernel_versions
config = Config('alembic.ini')
add_kernel_versions(config)
script = ScriptDirectory.from_config(config)
assert len(script.get_bases()) == 2
assert len(script.get_heads()) == 2
assert script.get_revision('service@head').revision == 'later'
""",
    )
    assert result.returncode == 0
