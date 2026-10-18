import json
from collections.abc import Mapping
from datetime import timedelta
from typing import Protocol, cast
from uuid import UUID

import asyncpg
from opentelemetry import propagate
from pgqueuer import AsyncpgDriver, Queries
from pgqueuer.errors import DuplicateJobError
from sqlalchemy import text

from fast_ddd.context import current_trace_id
from fast_ddd.serialization import JsonValue
from fast_ddd_adapter.observability import meter
from fast_ddd_adapter.session import current_session_provider


class TaskQueue(Protocol):
    """Background work that must not be lost: enqueued in the caller's transaction."""

    async def enqueue(
        self,
        task_name: str,
        data: Mapping[str, JsonValue],
        *,
        organization_id: UUID | None,
        delay: timedelta | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        """False when a job with the same ``dedupe_key`` is still waiting or running."""
        ...


TRACE_HEADER = "trace-id"
TASK_VERSION = 1

_enqueued = meter.create_counter(
    "fast_ddd.task.enqueued", unit="{task}", description="Tasks enqueued by committed transactions"
)


def task_body(data: Mapping[str, JsonValue], organization_id: UUID | None) -> bytes:
    body = {
        "taskVersion": TASK_VERSION,
        "organizationId": str(organization_id) if organization_id else None,
        "data": dict(data),
    }
    return json.dumps(body).encode()


class PgQueuerTaskQueue:
    """``TaskQueue`` on PgQueuer, using the SQLAlchemy session's own asyncpg connection.

    The job row is written in the same transaction as the business data, so a rollback
    removes the job too.
    """

    async def enqueue(
        self,
        task_name: str,
        data: Mapping[str, JsonValue],
        *,
        organization_id: UUID | None,
        delay: timedelta | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        provider = current_session_provider()
        session = provider.session
        raw = await (await session.connection()).get_raw_connection()
        driver_connection = cast(asyncpg.Connection, raw.driver_connection)
        if not driver_connection.is_in_transaction():
            # SQLAlchemy's asyncpg adapter sends BEGIN lazily on its own first statement; a raw
            # write before that would commit on its own, outside the caller's transaction.
            await session.execute(text("SELECT 1"))
        headers: dict[str, str] = {}
        if trace_id := current_trace_id():
            headers[TRACE_HEADER] = trace_id
        propagate.inject(headers)

        async def enqueue() -> None:
            await Queries(AsyncpgDriver(driver_connection)).enqueue(
                task_name,
                task_body(data, organization_id),
                execute_after=delay,
                dedupe_key=dedupe_key,
                headers=headers or None,
            )

        if dedupe_key is None:
            await enqueue()
        else:
            # A duplicate is a unique violation, which would abort the caller's transaction;
            # the SAVEPOINT confines it to this enqueue.
            try:
                async with provider.savepoint():
                    # The ORM emits SAVEPOINT lazily, at its next statement; this one runs on
                    # the raw connection, so ask for the connection to emit it now.
                    await session.connection()
                    await enqueue()
            except DuplicateJobError:
                return False

        async def count() -> None:
            _enqueued.add(1, {"task": task_name})

        provider.after_commit(count)
        return True
