import asyncio
import importlib
import os
from logging.config import fileConfig

from alembic import context
from fast_ddd_adapter.migrations import include_object
from fast_ddd_adapter.orm import Base
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Registers every table on Base.metadata; the service lists its model modules there.
importlib.import_module("app.adapter.repository.models")

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name)


def database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(database_url())
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
