import logging
import time
from collections.abc import Awaitable, Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import asyncpg
from opentelemetry import propagate
from opentelemetry.trace import SpanKind
from pgqueuer import AsyncpgDriver, PgQueuer, RetryRequested
from pgqueuer.models import Job, Schedule
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_ddd.context import User, unit_of_work_context
from fast_ddd.errors import DomainError, LockConflict
from fast_ddd_adapter.observability import meter, resolve_trace_id, tracer
from fast_ddd_adapter.session import SessionProvider, session_provider_scope
from fast_ddd_adapter.tasks import TRACE_HEADER
from fast_ddd_port.models import MessageModel

logger = logging.getLogger(__name__)


class TaskEnvelope(MessageModel):
    task_version: int
    organization_id: UUID | None
    data: dict[str, Any]


class TaskRejectedError(RuntimeError):
    """A deterministic failure: the job is kept as failed and not retried."""


_task_duration = meter.create_histogram(
    "fast_ddd.task.duration",
    unit="s",
    description="Task and schedule runs, by name and outcome (success, retried, failed)",
)


@contextmanager
def _observed(name: str, headers: Mapping[str, object]) -> Generator[None]:
    started = time.perf_counter()
    outcome = "failed"
    parent = propagate.extract(cast(Mapping[str, str], headers))
    try:
        with tracer.start_as_current_span(f"task {name}", context=parent, kind=SpanKind.CONSUMER):
            yield
        outcome = "success"
    except RetryRequested:
        outcome = "retried"
        raise
    finally:
        _task_duration.record(time.perf_counter() - started, {"task": name, "outcome": outcome})


type TaskHandler[T] = Callable[[TaskEnvelope, T], Awaitable[None]]
type ScheduledHandler = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _Task:
    payload: type[MessageModel]
    handler: TaskHandler[Any]


@dataclass(slots=True)
class TaskRegistry:
    tasks: dict[str, _Task] = field(default_factory=dict[str, _Task])
    schedules: dict[str, tuple[str, ScheduledHandler]] = field(
        default_factory=dict[str, tuple[str, ScheduledHandler]]
    )

    def task[T: MessageModel](self, name: str, payload: type[T], handler: TaskHandler[T]) -> None:
        self.tasks[name] = _Task(payload, handler)

    def cron(self, name: str, expression: str, handler: ScheduledHandler) -> None:
        self.schedules[name] = (expression, handler)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay: timedelta = timedelta(seconds=5)

    def retry_or_raise(self, job: Job, error: BaseException) -> None:
        if job.attempts < self.max_retries:
            raise RetryRequested(
                delay=self.base_delay * (2**job.attempts), reason=type(error).__name__
            ) from error
        raise error


async def _in_unit_of_work(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    organization_id: UUID | None,
    propagated_trace_id: object,
    work: Callable[[], Awaitable[None]],
) -> None:
    provider = SessionProvider(session_factory)
    with (
        unit_of_work_context(
            user=user,
            organization_id=organization_id,
            trace_id=resolve_trace_id(propagated_trace_id),
        ),
        session_provider_scope(provider),
    ):
        async with provider:
            await work()


def build_worker(
    connection: asyncpg.Connection,
    registry: TaskRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retry: RetryPolicy | None = None,
) -> PgQueuer:
    """PgQueuer worker whose jobs run behind the kernel wrapper (context, transaction, retries).

    Failed jobs are held (``on_failure="hold"``), never deleted, for inspection and re-runs.
    """
    policy = retry or RetryPolicy()
    worker = PgQueuer(AsyncpgDriver(connection))

    def job_handler(name: str, task: _Task) -> Callable[[Job], Awaitable[None]]:
        user = User(id=f"task:{name}")

        async def run(job: Job) -> None:
            headers = job.headers or {}
            with _observed(name, headers):
                await attempt(job, headers)

        async def attempt(job: Job, headers: Mapping[str, object]) -> None:
            try:
                envelope = TaskEnvelope.model_validate_json(job.payload or b"{}")
                data = task.payload.model_validate(envelope.data)
            except ValidationError as error:
                raise TaskRejectedError(f"malformed payload for {name}") from error
            try:
                await _in_unit_of_work(
                    session_factory,
                    user=user,
                    organization_id=envelope.organization_id,
                    propagated_trace_id=headers.get(TRACE_HEADER),
                    work=lambda: task.handler(envelope, data),
                )
            except LockConflict as error:
                policy.retry_or_raise(job, error)
            except DomainError as error:
                raise TaskRejectedError(error.error_code) from error
            except Exception as error:
                logger.warning("task %s failed (attempt %s)", name, job.attempts, exc_info=True)
                policy.retry_or_raise(job, error)

        return run

    def schedule_handler(
        name: str, handler: ScheduledHandler
    ) -> Callable[[Schedule], Awaitable[None]]:
        user = User(id=f"schedule:{name}")

        async def run(_: Schedule) -> None:
            with _observed(name, {}):
                await _in_unit_of_work(
                    session_factory,
                    user=user,
                    organization_id=None,
                    propagated_trace_id=None,
                    work=handler,
                )

        return run

    for name, task in registry.tasks.items():
        worker.entrypoint(name, on_failure="hold")(job_handler(name, task))
    for name, (expression, handler) in registry.schedules.items():
        worker.schedule(name, expression)(schedule_handler(name, handler))
    return worker
