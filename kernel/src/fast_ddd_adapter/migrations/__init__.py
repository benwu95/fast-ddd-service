import os
from argparse import Namespace
from collections.abc import Sequence
from pathlib import Path

from alembic import op
from alembic.config import CommandLine, Config
from sqlalchemy.engine.interfaces import AdaptedConnection

BRANCH_LABEL = "fast_ddd"


def version_location() -> str:
    """Directory to add to the service's Alembic ``version_locations``."""
    return str(Path(__file__).parent / "versions")


PGQUEUER_TABLE_PREFIX = "pgqueuer"


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object | None
) -> bool:
    """Alembic ``include_object``: PgQueuer's tables are managed by raw SQL, not by models."""
    del obj, compare_to
    return not (type_ == "table" and reflected and (name or "").startswith(PGQUEUER_TABLE_PREFIX))


def execute_script(sql: str) -> None:
    """Run a multi-statement SQL script (asyncpg rejects them as prepared statements)."""
    dbapi_connection = op.get_bind().connection.dbapi_connection
    if isinstance(dbapi_connection, AdaptedConnection):
        dbapi_connection.run_async(lambda driver: driver.execute(sql))
    else:
        op.execute(sql)


def add_kernel_versions(config: Config) -> None:
    """Append the kernel's version location; the service's ``alembic.ini`` must use
    ``path_separator = os``.

    Alembic reads ``version_locations`` before ``env.py`` runs, so this has to happen on the
    ``Config`` itself (the ``fast-ddd-alembic`` command, or tests building a ``Config``).
    """
    kernel = version_location()
    locations = config.get_main_option("version_locations")
    if locations is None:
        locations = str(Path(config.get_main_option("script_location") or "") / "versions")
    if kernel not in locations.split(os.pathsep):
        config.set_main_option("version_locations", f"{locations}{os.pathsep}{kernel}")


class _CommandLine(CommandLine):
    def run_cmd(self, config: Config, options: Namespace) -> None:
        add_kernel_versions(config)
        super().run_cmd(config, options)


def main(argv: Sequence[str] | None = None) -> None:
    """``alembic`` with the kernel's migrations included; takes the same arguments."""
    _CommandLine(prog="fast-ddd-alembic").main(argv)
