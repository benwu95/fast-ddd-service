import json
import logging
import sys
import time
import traceback
from collections.abc import Iterable
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Protocol, cast
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pendulum
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from sqlalchemy import event
from sqlalchemy.engine import Connection, ExceptionContext
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from fast_ddd.context import (
    ContextNotSetError,
    current_organization_id,
    current_trace_id,
    current_user,
)
from fast_ddd.serialization import format_datetime

meter = metrics.get_meter("fast_ddd")
tracer = trace.get_tracer("fast_ddd")

type TelemetryExporter = Literal["none", "console", "otlp"]


class _MetricShutdown(Protocol):
    # The SDK metric shutdown methods expose unused, unannotated **kwargs.
    def shutdown(self) -> None: ...


def current_otel_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def resolve_trace_id(propagated: object = None) -> str:
    """The trace id carried by the message, else the active OpenTelemetry one, else a new one.

    When the sender had a span, the carried id and the propagated span's trace id are the same.
    """
    return (str(propagated) if propagated else None) or current_otel_trace_id() or uuid4().hex


@dataclass(frozen=True, slots=True)
class Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def shutdown(self) -> None:
        try:
            self.tracer_provider.shutdown()
        finally:
            self.meter_provider.shutdown()


def build_telemetry(service_name: str, exporter: TelemetryExporter) -> Telemetry:
    """SDK providers are always built, so trace ids exist and propagate even with no exporter.

    The OTLP endpoint and headers come from the standard ``OTEL_EXPORTER_OTLP_*`` variables.
    """
    resource = Resource.create({SERVICE_NAME: service_name})
    with ExitStack() as pending:
        tracer_provider = TracerProvider(resource=resource)
        pending.callback(tracer_provider.shutdown)
        readers: list[MetricReader] = []
        if exporter != "none":
            with ExitStack() as span_pending:
                span_exporter = OTLPSpanExporter() if exporter == "otlp" else ConsoleSpanExporter()
                span_pending.callback(span_exporter.shutdown)
                processor = BatchSpanProcessor(span_exporter)
                span_pending.pop_all()
            with ExitStack() as processor_pending:
                processor_pending.callback(processor.shutdown)
                tracer_provider.add_span_processor(processor)
                processor_pending.pop_all()
            with ExitStack() as metric_pending:
                metric_exporter = (
                    OTLPMetricExporter() if exporter == "otlp" else ConsoleMetricExporter()
                )
                metric_pending.callback(cast(_MetricShutdown, metric_exporter).shutdown)
                reader = PeriodicExportingMetricReader(metric_exporter)
                metric_pending.pop_all()
            pending.callback(cast(_MetricShutdown, reader).shutdown)
            readers.append(reader)
        meter_provider = MeterProvider(resource=resource, metric_readers=readers)
        pending.pop_all()
        return Telemetry(tracer_provider, meter_provider)


def setup_telemetry(service_name: str, exporter: TelemetryExporter) -> Telemetry:
    """Install the process-wide providers once at startup; call ``shutdown()`` on exit."""
    telemetry = build_telemetry(service_name, exporter)
    try:
        trace.set_tracer_provider(telemetry.tracer_provider)
        metrics.set_meter_provider(telemetry.meter_provider)
    except BaseException:
        telemetry.shutdown()
        raise
    return telemetry


_RECORD_ATTRIBUTES = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys() | {"message", "asctime"}
)


def _context_fields() -> dict[str, str]:
    fields: dict[str, str] = {}
    if trace_id := current_trace_id() or current_otel_trace_id():
        fields["trace_id"] = trace_id
    with suppress(ContextNotSetError):
        fields["user_id"] = current_user().id
    with suppress(ContextNotSetError):
        if organization_id := current_organization_id():
            fields["organization_id"] = str(organization_id)
    return fields


def _exception_diagnostics(error: BaseException, tb: TracebackType | None) -> str:
    # Exception values, source lines and locals may contain request bodies or credentials.
    seen: set[int] = set()

    def render(current: BaseException, current_tb: TracebackType | None) -> list[str]:
        if id(current) in seen:
            return []
        seen.add(id(current))
        lines: list[str] = []
        if current.__cause__ is not None:
            lines.extend(render(current.__cause__, current.__cause__.__traceback__))
            lines.append("The above exception was the direct cause:")
        elif current.__context__ is not None and not current.__suppress_context__:
            lines.extend(render(current.__context__, current.__context__.__traceback__))
            lines.append("During handling of the above exception:")
        if current_tb is not None:
            lines.append("Traceback (most recent call last):")
            for frame, lineno in traceback.walk_tb(current_tb):
                lines.append(
                    f'  File "{frame.f_code.co_filename}", line {lineno}, in {frame.f_code.co_name}'
                )
        lines.append(f"{type(current).__module__}.{type(current).__qualname__}")
        if isinstance(current, BaseExceptionGroup):
            for nested in cast(BaseExceptionGroup[BaseException], current).exceptions:
                lines.extend(render(nested, nested.__traceback__))
        return lines

    return "\n".join(render(error, tb))


_LIBRARY_LOGGERS = frozenset(
    {
        "uvicorn",
        "faststream",
        "pgqueuer",
        "aio_pika",
        "aiormq",
        "httpx2",
        "httpcore",
        "httpcore2",
        "sqlalchemy",
        "asyncpg",
        "asyncio",
        "opentelemetry",
        "urllib3",
    }
)
_QUIET_LOGGERS = _LIBRARY_LOGGERS - {"uvicorn", "faststream", "pgqueuer", "asyncio"}


def _library_fields(record: logging.LogRecord) -> dict[str, Any]:
    # Library messages may already contain rendered bodies, URLs or traceback values.
    fields: dict[str, Any] = {
        "message": "library operation failed"
        if record.levelno >= logging.ERROR
        else "library event",
        "code.function": record.funcName,
        "code.filepath": record.pathname,
        "code.lineno": record.lineno,
    }
    if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
        client, method, target, version, status = record.args
        try:
            path = urlsplit(unquote(str(target).partition("?")[0])).path
        except ValueError:
            path = "[invalid]"
        fields |= {
            "message": "HTTP request",
            "client.address": client,
            "http.request.method": method,
            "url.path": path,
            "network.protocol.version": version,
            "http.response.status_code": status,
        }
    values = (record.msg, *(record.args if isinstance(record.args, tuple) else ()))
    for value in values:
        if isinstance(value, BaseException):
            fields["exception"] = _exception_diagnostics(value, value.__traceback__)
            break
    return fields


class JsonFormatter(logging.Formatter):
    """JSON records with unit-of-work context and controlled library metadata."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": format_datetime(pendulum.from_timestamp(record.created, tz="UTC")),
            "level": record.levelname,
            "logger": record.name,
            "message": "",
            **_context_fields(),
        }
        if record.name.split(".")[0] in _LIBRARY_LOGGERS:
            entry |= _library_fields(record)
        else:
            entry["message"] = record.getMessage()
            entry |= {k: v for k, v in record.__dict__.items() if k not in _RECORD_ATTRIBUTES}
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = _exception_diagnostics(record.exc_info[1], record.exc_info[2])
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    names = _LIBRARY_LOGGERS | set(logging.root.manager.loggerDict)
    for name in names:
        family = name.split(".")[0]
        if family in _LIBRARY_LOGGERS:
            library = logging.getLogger(name)
            library.handlers.clear()
            library.propagate = True
            library.disabled = False
            library.setLevel(logging.WARNING if name in _QUIET_LOGGERS else logging.NOTSET)


_db_duration = meter.create_histogram(
    "db.client.operation.duration", unit="s", description="Duration of database statements"
)
_QUERY_STARTED = "fast_ddd_query_started"


def _query_started(*args: Any) -> None:
    connection: Connection = args[0]
    connection.info.setdefault(_QUERY_STARTED, []).append(time.perf_counter())


def _record_query(connection: Connection, pool_name: str, error: str | None) -> None:
    started: list[float] = connection.info.get(_QUERY_STARTED, [])
    if not started:
        return
    attributes = {"db.system.name": "postgresql", "db.client.connection.pool.name": pool_name}
    if error:
        attributes["error.type"] = error
    _db_duration.record(time.perf_counter() - started.pop(), attributes)


def instrument_engine(engine: AsyncEngine, *, pool_name: str, max_connections: int) -> None:
    """Statement durations and connection pool usage, reported as OpenTelemetry metrics.

    SQLAlchemy does not expose how many callers wait for a connection; pool exhaustion shows
    up as ``used`` reaching ``db.client.connection.max``.
    """
    pool = engine.pool
    attributes = {"db.client.connection.pool.name": pool_name}

    def connection_counts(_: CallbackOptions) -> Iterable[Observation]:
        if isinstance(pool, QueuePool):
            yield Observation(
                pool.checkedout(), {**attributes, "db.client.connection.state": "used"}
            )
            yield Observation(
                pool.checkedin(), {**attributes, "db.client.connection.state": "idle"}
            )

    def connection_max(_: CallbackOptions) -> Iterable[Observation]:
        yield Observation(max_connections, attributes)

    meter.create_observable_up_down_counter(
        "db.client.connection.count", [connection_counts], unit="{connection}"
    )
    meter.create_observable_up_down_counter(
        "db.client.connection.max", [connection_max], unit="{connection}"
    )

    def query_finished(*args: Any) -> None:
        _record_query(args[0], pool_name, None)

    def query_failed(context: ExceptionContext) -> None:
        if context.connection is not None:
            # The dialect wraps driver errors in a generic class; the cause names the failure.
            error = context.original_exception.__cause__ or context.original_exception
            _record_query(context.connection, pool_name, type(error).__name__)

    event.listen(engine.sync_engine, "before_cursor_execute", _query_started)
    event.listen(engine.sync_engine, "after_cursor_execute", query_finished)
    event.listen(engine.sync_engine, "handle_error", query_failed)
