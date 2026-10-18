import asyncio

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.runtime.conftest import alembic_config


def test_each_branch_has_exactly_one_head(database_url: str) -> None:
    script = ScriptDirectory.from_config(alembic_config(database_url))

    heads = [script.get_revision(head) for head in script.get_heads()]

    assert sorted(label for head in heads if head for label in head.branch_labels) == [
        "fast_ddd",
        "service",
    ]


async def test_models_have_no_pending_migration(database_url: str) -> None:
    await asyncio.to_thread(command.check, alembic_config(database_url))


async def test_service_branch_downgrades_and_upgrades(database_url: str) -> None:
    admin = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text("DROP DATABASE IF EXISTS migration_round_trip"))
        await connection.execute(text("CREATE DATABASE migration_round_trip"))
    await admin.dispose()
    config = alembic_config(database_url.rsplit("/", 1)[0] + "/migration_round_trip")

    await asyncio.to_thread(command.upgrade, config, "heads")
    await asyncio.to_thread(command.downgrade, config, "service@base")
    await asyncio.to_thread(command.upgrade, config, "heads")
    await asyncio.to_thread(command.check, config)
