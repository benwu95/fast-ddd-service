import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

from alembic import command
from alembic.autogenerate import compare_metadata, render_python_code
from alembic.autogenerate.api import AutogenContext
from alembic.config import Config
from alembic.operations import ops
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Connection, Integer, MetaData, String, Table, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.types import TypeDecorator

from fast_ddd_adapter.migrations import (
    BRANCH_LABEL,
    add_kernel_versions,
    include_object,
    render_item,
    version_location,
)
from fast_ddd_adapter.orm import (
    NAMING_CONVENTION,
    DomainEventModel,
    ProcessedMessage,
    UtcDateTime,
)
from tests.conftest import alembic_config

ENV_PY = """
import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

def run(connection):
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()

async def main():
    engine = create_async_engine(context.config.get_main_option("sqlalchemy.url"))
    async with engine.connect() as connection:
        await connection.run_sync(run)
        await connection.commit()
    await engine.dispose()

asyncio.run(main())
"""


def _kernel_metadata() -> MetaData:
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    for model in (DomainEventModel, ProcessedMessage):
        cast(Table, model.__table__).to_metadata(metadata)
    return metadata


def _diff(connection: Connection) -> list[object]:
    context = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            "compare_server_default": True,
            "include_object": include_object,
        },
    )
    return list(compare_metadata(context, _kernel_metadata()))


async def test_kernel_migration_matches_models(database_url: str, tmp_path: Path) -> None:
    admin = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text("DROP DATABASE IF EXISTS kernel_migration"))
        await connection.execute(text("CREATE DATABASE kernel_migration"))
    await admin.dispose()
    url = database_url.rsplit("/", 1)[0] + "/kernel_migration"

    script_dir = tmp_path / "migrations"
    script_dir.mkdir()
    (script_dir / "env.py").write_text(ENV_PY)
    (script_dir / "script.py.mako").write_text("")
    config = Config()
    config.set_main_option("script_location", str(script_dir))
    config.set_main_option("path_separator", "os")
    config.set_main_option("version_locations", version_location())
    config.set_main_option("sqlalchemy.url", url)

    await asyncio.to_thread(command.upgrade, config, f"{BRANCH_LABEL}@head")

    engine = create_async_engine(url)
    async with engine.connect() as connection:
        diff = await connection.run_sync(_diff)
    await engine.dispose()
    assert diff == []
    await asyncio.to_thread(command.downgrade, config, "base")
    await asyncio.to_thread(command.upgrade, config, f"{BRANCH_LABEL}@head")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        assert await connection.run_sync(_diff) == []
    await engine.dispose()


async def test_fixture_uses_migrations_matching_all_registered_models(database_url: str) -> None:
    config = alembic_config(database_url)
    script = ScriptDirectory.from_config(config)
    assert set(script.get_heads()) == {"fastddd_0003", "kernel_test_0001"}
    kernel_head = script.get_revision("fast_ddd@head")
    assert kernel_head is not None
    assert kernel_head.revision == "fastddd_0003"
    await asyncio.to_thread(command.check, config)


def test_kernel_versions_are_added_once(tmp_path: Path) -> None:
    config = Config()
    config.set_main_option("script_location", str(tmp_path))

    add_kernel_versions(config)
    add_kernel_versions(config)

    locations = (config.get_main_option("version_locations") or "").split(os.pathsep)
    assert locations == [str(tmp_path / "versions"), version_location()]


def test_cli_lists_kernel_heads(tmp_path: Path) -> None:
    script_dir = tmp_path / "alembic"
    (script_dir / "versions").mkdir(parents=True)
    ini = tmp_path / "alembic.ini"
    ini.write_text(f"[alembic]\nscript_location = {script_dir}\npath_separator = os\n")

    result = subprocess.run(
        [Path(sys.executable).parent / "fast-ddd-alembic", "-c", str(ini), "heads"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "fastddd_0003 (fast_ddd) (head)" in result.stdout


class _OtherType(TypeDecorator[str]):
    impl = String()
    cache_ok = True


def test_utc_datetime_renders_as_sqlalchemy_datetime() -> None:
    upgrade = ops.UpgradeOps(
        ops=[
            ops.CreateTableOp(
                "record",
                [Column("id", Integer, primary_key=True), Column("created_at", UtcDateTime())],
            ),
            ops.ModifyTableOps(
                "record",
                [
                    ops.AlterColumnOp(
                        "record",
                        "created_at",
                        existing_type=UtcDateTime(),
                        modify_nullable=False,
                    )
                ],
            ),
        ]
    )

    code = render_python_code(upgrade, render_item=render_item)

    assert "sa.Column('created_at', sa.DateTime(timezone=True)" in code
    assert "existing_type=sa.DateTime(timezone=True)" in code
    assert "fast_ddd_adapter" not in code


def test_utc_datetime_follows_the_configured_sqlalchemy_prefix() -> None:
    upgrade = ops.UpgradeOps(
        ops=[ops.CreateTableOp("record", [Column("created_at", UtcDateTime())])]
    )

    code = render_python_code(upgrade, sqlalchemy_module_prefix="sqla.", render_item=render_item)

    assert "sqla.Column('created_at', sqla.DateTime(timezone=True)" in code


def test_render_item_defers_everything_else_to_alembic() -> None:
    context = AutogenContext(MigrationContext.configure(dialect_name="postgresql"))

    assert render_item("type", String(), context) is False
    assert render_item("type", _OtherType(), context) is False
