import io
import json
import logging
import threading
from collections.abc import Callable, Generator
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from fast_ddd.context import User, unit_of_work_context
from fast_ddd_adapter import observability
from fast_ddd_adapter.http_client import create_http_client, redact_url
from fast_ddd_adapter.observability import (
    JsonFormatter,
    TelemetryExporter,
    build_telemetry,
    configure_logging,
    resolve_trace_id,
    setup_telemetry,
)
from fast_ddd_adapter.observability import (
    Telemetry as RuntimeTelemetry,
)
from fast_ddd_port.models import MessageModel
from fast_ddd_port.subscriber import kernel_queue, subscribe
from tests.telemetry import Telemetry, span_trace_id

type Handler = Callable[[httpx2.Request], httpx2.Response]


@pytest.fixture
def json_log() -> Generator[tuple[logging.Logger, io.StringIO]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("tests.json")
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.INFO)
    yield logger, stream
    logger.removeHandler(handler)


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_log_carries_unit_of_work_context_extras_and_exception(
    json_log: tuple[logging.Logger, io.StringIO], organization_id: UUID
) -> None:
    logger, stream = json_log
    with unit_of_work_context(
        user=User(id="u-1"), organization_id=organization_id, trace_id="trace-9"
    ):
        logger.info("voided %s", "order", extra={"order_id": "o-1"})
        try:
            raise ValueError("bad")
        except ValueError:
            logger.exception("failed")
    logger.warning("outside")

    voided, failed, outside = lines(stream)
    assert voided["message"] == "voided order"
    assert voided["level"] == "INFO"
    assert voided["timestamp"].endswith("Z")
    assert (voided["trace_id"], voided["user_id"], voided["organization_id"]) == (
        "trace-9",
        "u-1",
        str(organization_id),
    )
    assert voided["order_id"] == "o-1"
    assert "ValueError" in failed["exception"]
    assert "bad" not in failed["exception"]
    assert {"trace_id", "user_id", "organization_id"}.isdisjoint(outside)


def test_json_log_falls_back_to_the_active_span(
    json_log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = json_log
    with span_trace_id() as trace_id:
        logger.info("in span")

    assert lines(stream)[0]["trace_id"] == trace_id


def test_configure_logging_replaces_root_handlers() -> None:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        configure_logging("DEBUG")
        assert [type(h.formatter) for h in root.handlers] == [JsonFormatter]
        assert root.level == logging.DEBUG
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


def test_trace_id_prefers_the_propagated_one_then_the_active_span() -> None:
    with span_trace_id() as trace_id:
        assert resolve_trace_id("carried") == "carried"
        assert resolve_trace_id(None) == trace_id
    assert len(resolve_trace_id()) == 32


@pytest.mark.parametrize("exporter", ["none", "console", "otlp"])
def test_build_telemetry_for_each_exporter(
    exporter: TelemetryExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "1")
    telemetry = build_telemetry("svc", exporter)
    assert telemetry.tracer_provider.resource.attributes["service.name"] == "svc"
    telemetry.shutdown()


@pytest.mark.parametrize("stage", ["processor", "attach", "metric_exporter", "reader", "meter"])
def test_partial_telemetry_construction_stops_started_exporter_threads(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = set(threading.enumerate())
    providers: list[observability.TracerProvider] = []
    readers: list[observability.PeriodicExportingMetricReader] = []
    original = observability.TracerProvider
    original_reader = observability.PeriodicExportingMetricReader

    def provider(*args: Any, **kwargs: Any) -> observability.TracerProvider:
        created = original(*args, **kwargs)
        providers.append(created)
        if stage == "attach":
            monkeypatch.setattr(
                created, "add_span_processor", Mock(side_effect=ValueError("attach"))
            )
        return created

    def reader(*args: Any, **kwargs: Any) -> observability.PeriodicExportingMetricReader:
        created = original_reader(*args, **kwargs)
        readers.append(created)
        return created

    monkeypatch.setattr(observability, "TracerProvider", provider)
    monkeypatch.setattr(observability, "PeriodicExportingMetricReader", reader)
    if stage == "reader":
        monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL", "-1")
    elif stage in {"processor", "metric_exporter"}:
        target = "BatchSpanProcessor" if stage == "processor" else "ConsoleMetricExporter"
        monkeypatch.setattr(observability, target, Mock(side_effect=ValueError(stage)))
    elif stage == "attach":
        pass
    else:
        monkeypatch.setattr(observability, "MeterProvider", Mock(side_effect=ValueError("meter")))
    try:
        with pytest.raises(ValueError, match="interval value" if stage == "reader" else stage):
            build_telemetry("partial-test", "console")
        assert not (set(threading.enumerate()) - previous)
    finally:
        for created in providers:
            created.shutdown()
        for created_reader in readers:
            cast(Any, created_reader).shutdown()


def test_failed_provider_installation_shuts_down_both_created_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry = Mock(spec=RuntimeTelemetry)
    monkeypatch.setattr(observability, "build_telemetry", Mock(return_value=telemetry))
    monkeypatch.setattr(observability.trace, "set_tracer_provider", Mock())
    monkeypatch.setattr(
        observability.metrics, "set_meter_provider", Mock(side_effect=ValueError("install"))
    )
    with pytest.raises(ValueError, match="install"):
        setup_telemetry("failed-install", "none")
    telemetry.shutdown.assert_called_once()


def test_telemetry_shutdown_closes_metrics_when_trace_shutdown_fails() -> None:
    traces, metrics = Mock(), Mock()
    traces.shutdown.side_effect = ValueError("trace shutdown")
    telemetry = RuntimeTelemetry(traces, metrics)
    with pytest.raises(ValueError, match="trace shutdown"):
        telemetry.shutdown()
    metrics.shutdown.assert_called_once()


async def test_database_metrics(engine: AsyncEngine, telemetry: Telemetry) -> None:
    def statements(**attributes: Any) -> float:
        return telemetry.total(
            "db.client.operation.duration",
            **{"db.client.connection.pool.name": "kernel-tests"},
            **attributes,
        )

    before_ok = statements()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        with pytest.raises(DBAPIError):
            await connection.execute(text("SELECT 1 / 0"))
        states = {
            attributes["db.client.connection.state"]: value
            for attributes, value in telemetry.points("db.client.connection.count")
            if attributes["db.client.connection.pool.name"] == "kernel-tests"
        }

    assert statements() - before_ok >= 2
    assert statements(**{"error.type": "DivisionByZeroError"}) >= 1
    assert states["used"] >= 1
    maximum = [
        value
        for attributes, value in telemetry.points("db.client.connection.max")
        if attributes["db.client.connection.pool.name"] == "kernel-tests"
    ]
    assert maximum == [15]


def client_with(handler: Handler, *, retries: int = 2) -> httpx2.AsyncClient:
    return create_http_client(
        "billing",
        base_url="https://billing.test",
        timeout=1.0,
        retries=retries,
        retry_delay=0,
        transport=httpx2.MockTransport(handler),
    )


def failing_then(response: httpx2.Response, failures: int) -> tuple[Handler, list[str]]:
    calls: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.method)
        if len(calls) <= failures:
            raise httpx2.ConnectError("refused", request=request)
        return response

    return handle, calls


async def test_idempotent_requests_retry_connection_failures() -> None:
    handler, calls = failing_then(httpx2.Response(200), failures=2)
    async with client_with(handler) as client:
        response = await client.get("/invoices")

    assert response.status_code == 200
    assert calls == ["GET", "GET", "GET"]


async def test_retries_are_bounded() -> None:
    handler, calls = failing_then(httpx2.Response(200), failures=5)
    async with client_with(handler, retries=1) as client:
        with pytest.raises(httpx2.ConnectError):
            await client.delete("/invoices/1")

    assert calls == ["DELETE", "DELETE"]


async def test_non_idempotent_requests_and_responses_are_not_retried() -> None:
    handler, calls = failing_then(httpx2.Response(200), failures=1)
    async with client_with(handler) as client:
        with pytest.raises(httpx2.ConnectError):
            await client.post("/invoices", json={})
    assert calls == ["POST"]

    handler, calls = failing_then(httpx2.Response(503), failures=0)
    async with client_with(handler) as client:
        response = await client.get("/invoices")
    assert response.status_code == 503
    assert calls == ["GET"]


async def test_outbound_calls_propagate_trace_and_are_logged_redacted(
    telemetry: Telemetry, caplog: pytest.LogCaptureFixture
) -> None:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200)

    before = telemetry.total("http.client.request.duration", **{"service.peer.name": "billing"})
    caplog.set_level(logging.INFO, logger="fast_ddd_adapter.http_client")
    async with client_with(handle) as client:
        with span_trace_id() as trace_id:
            await client.get("/invoices", params={"access_token": "s3cret", "page": "2"})

    assert trace_id in seen[0].headers["traceparent"]
    record = caplog.records[-1]
    assert record.__dict__["url.full"] == (
        "https://billing.test/invoices?access_token=REDACTED&page=2"
    )
    assert record.__dict__["http.response.status_code"] == 200
    assert "s3cret" not in caplog.text
    after = telemetry.total("http.client.request.duration", **{"service.peer.name": "billing"})
    assert after - before == 1


def test_redact_url_drops_credentials_and_masks_secrets() -> None:
    url = httpx2.URL("https://user:pw@api.test/x?apiKey=k&q=shoes&signature=s")
    assert redact_url(url) == "https://api.test/x?apiKey=REDACTED&q=shoes&signature=REDACTED"
    assert redact_url(httpx2.URL("https://api.test/x")) == "https://api.test/x"


@pytest.mark.parametrize("status", [200, 503])
async def test_outbound_duration_is_classified_by_response_status(
    status: int,
    telemetry: Telemetry,
) -> None:
    attributes = {"service.peer.name": "billing", "http.response.status_code": status}
    before = telemetry.total("http.client.request.duration", **attributes)
    async with client_with(lambda _: httpx2.Response(status)) as client:
        assert (await client.get("/invoices")).status_code == status
    assert telemetry.total("http.client.request.duration", **attributes) - before == 1


@pytest.mark.parametrize(
    "error_type", [httpx2.ConnectError, httpx2.ReadTimeout, httpx2.WriteTimeout]
)
async def test_transport_failures_are_bounded_classified_and_redacted(
    error_type: type[httpx2.TransportError],
    telemetry: Telemetry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def fail(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        raise error_type("network sentinel", request=request)

    attributes = {"service.peer.name": "billing", "error.type": error_type.__name__}
    before = telemetry.total("http.client.request.duration", **attributes)
    with caplog.at_level(logging.WARNING, logger="fast_ddd_adapter.http_client"):
        async with client_with(fail, retries=1) as client:
            with pytest.raises(error_type):
                await client.get("/invoices?apiKey=secret-sentinel")
    assert calls == 2
    assert telemetry.total("http.client.request.duration", **attributes) - before == 1
    assert caplog.records[-1].__dict__["url.full"].endswith("apiKey=REDACTED")
    assert "secret-sentinel" not in caplog.text


async def test_outbound_client_applies_timeouts_and_closes_its_transport() -> None:
    class Transport(httpx2.AsyncBaseTransport):
        def __init__(self) -> None:
            self.closed = False
            self.timeouts: Any = None

        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            self.timeouts = request.extensions["timeout"]
            return httpx2.Response(204)

        async def aclose(self) -> None:
            self.closed = True

    transport = Transport()
    async with create_http_client(
        "billing", base_url="https://billing.test", timeout=1.5, transport=transport
    ) as client:
        await client.put("/notifications/key", json={})
        assert transport.timeouts == {"connect": 1.5, "read": 1.5, "write": 1.5, "pool": 1.5}
        assert not transport.closed
    assert transport.closed


@pytest.fixture
def process_json_log(monkeypatch: pytest.MonkeyPatch) -> Generator[io.StringIO]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    libraries = [
        logging.getLogger(name)
        for name in ("httpx2", "httpcore", "faststream", "faststream.access.rabbit", "pgqueuer")
    ]
    states = [(logger.level, logger.handlers[:], logger.propagate) for logger in libraries]
    stream = io.StringIO()
    monkeypatch.setattr("sys.stdout", stream)
    configure_logging()
    try:
        yield stream
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        for logger, (saved_level, saved_handlers, propagated) in zip(
            libraries, states, strict=True
        ):
            logger.setLevel(saved_level)
            logger.handlers[:] = saved_handlers
            logger.propagate = propagated


async def test_process_json_logs_exclude_parallel_http_client_sensitive_url(
    process_json_log: io.StringIO,
) -> None:
    async with client_with(lambda _: httpx2.Response(200)) as client:
        await client.get("/invoices?access_token=OUTBOUND_PRIVATE_TOKEN&page=2")
    output = process_json_log.getvalue()
    assert "OUTBOUND_PRIVATE_TOKEN" not in output
    assert any(
        record["url.full"].endswith("access_token=REDACTED&page=2")
        for record in lines(process_json_log)
        if "url.full" in record
    )


async def test_process_json_logs_exclude_mq_validation_body(
    process_json_log: io.StringIO,
) -> None:
    broker = AsyncMock()
    registered: list[Any] = []
    broker.subscriber = Mock(return_value=registered.append)

    class Payload(MessageModel):
        code: str

    subscribe(
        broker,
        name="secret-test",
        queue=kernel_queue("secret-test", routing_key="event"),
        exchange="test",
        payload=Payload,
        handler=AsyncMock(),
        session_factory=AsyncMock(),
    )
    message = AsyncMock()
    await registered[0](b'{"password":"MQ_PRIVATE_PASSWORD"}', message)
    message.reject.assert_awaited_once_with(requeue=False)
    assert "MQ_PRIVATE_PASSWORD" not in process_json_log.getvalue()
    assert "ValidationError" in process_json_log.getvalue()


def test_json_exception_chain_preserves_frames_and_types_without_values(
    json_log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = json_log
    try:
        try:
            raise ValueError("BODY_PRIVATE_PASSWORD")
        except ValueError as error:
            raise RuntimeError("https://test/?access_token=CHAIN_PRIVATE_TOKEN") from error
    except RuntimeError:
        logger.exception("request failed")
    output = stream.getvalue()
    assert "BODY_PRIVATE_PASSWORD" not in output
    assert "CHAIN_PRIVATE_TOKEN" not in output
    failure = lines(stream)[0]["exception"]
    assert "ValueError" in failure
    assert "RuntimeError" in failure
    assert "test_json_exception_chain_preserves_frames_and_types_without_values" in failure
    assert "test_observability.py" in failure


def test_setup_telemetry_installs_both_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    traces, metrics = Mock(), Mock()
    monkeypatch.setattr("fast_ddd_adapter.observability.trace.set_tracer_provider", traces)
    monkeypatch.setattr("fast_ddd_adapter.observability.metrics.set_meter_provider", metrics)
    telemetry = setup_telemetry("setup-test", "none")
    try:
        traces.assert_called_once_with(telemetry.tracer_provider)
        metrics.assert_called_once_with(telemetry.meter_provider)
    finally:
        telemetry.shutdown()


def test_json_exception_groups_and_implicit_context_exclude_sensitive_values(
    json_log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = json_log

    def fail_group() -> None:
        raise ExceptionGroup("GROUP_PRIVATE_PASSWORD", [TypeError("NESTED_PRIVATE_PASSWORD")])

    try:
        try:
            raise ValueError("CONTEXT_PRIVATE_PASSWORD")
        except ValueError:
            fail_group()
    except ExceptionGroup:
        logger.exception("task failed")
    output = stream.getvalue()
    assert "PRIVATE_PASSWORD" not in output
    failure = lines(stream)[0]["exception"]
    assert all(name in failure for name in ("ValueError", "ExceptionGroup", "TypeError"))


def test_configure_logging_disables_http_library_payload_debug_logs(
    process_json_log: io.StringIO,
) -> None:
    configure_logging("DEBUG")
    logging.getLogger("httpcore").debug("Authorization: DEBUG_PRIVATE_TOKEN")
    assert "DEBUG_PRIVATE_TOKEN" not in process_json_log.getvalue()
    assert logging.getLogger("httpx2").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


@pytest.mark.parametrize("name", ["faststream.access.rabbit", "pgqueuer"])
def test_library_failure_messages_exclude_rendered_exception_or_payload(
    process_json_log: io.StringIO,
    name: str,
) -> None:
    try:
        raise ValueError("LIBRARY_PRIVATE_PASSWORD")
    except ValueError as error:
        logging.getLogger(name).error(
            "processing body %s: %s", "BODY_PRIVATE_PASSWORD", error, exc_info=error
        )
    output = process_json_log.getvalue()
    assert "PRIVATE_PASSWORD" not in output
    assert "ValueError" in output
