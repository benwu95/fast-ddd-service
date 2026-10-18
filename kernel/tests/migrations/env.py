import asyncio
import importlib

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from fast_ddd_adapter.migrations import include_object
from fast_ddd_adapter.orm import Base

importlib.import_module("tests.adapter.models")


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
    engine = create_async_engine(context.config.get_main_option("sqlalchemy.url") or "")
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
            await connection.commit()
    finally:
        await engine.dispose()


asyncio.run(run_online())
