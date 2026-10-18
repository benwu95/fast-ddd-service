import asyncio
import io
import json
import logging
import sys
from collections.abc import Generator
from typing import Any
from unittest.mock import Mock

import h11
import pytest
import uvicorn
from httpcore2._trace import Trace
from uvicorn.lifespan.on import LifespanOn
from uvicorn.protocols.http.flow_control import FlowControl
from uvicorn.protocols.http.h11_impl import RequestResponseCycle

from fast_ddd_adapter.observability import configure_logging


@pytest.fixture
def process_output(monkeypatch: pytest.MonkeyPatch) -> Generator[io.StringIO]:
    names = list(logging.root.manager.loggerDict)
    names += [
        "",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "httpcore2.http11",
        "aiormq.channel",
    ]
    states = {
        name: (logger.handlers[:], logger.level, logger.propagate, logger.disabled)
        for name in set(names)
        if (logger := logging.getLogger(name))
    }
    stream = io.StringIO()
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr("sys.stderr", stream)
    yield stream
    for name, (handlers, level, propagate, disabled) in states.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate
        logger.disabled = disabled


def configure_server(worker: bool, stream: io.StringIO) -> uvicorn.Config:
    sys.stdout = stream
    sys.stderr = stream

    async def app(scope: Any, receive: Any, send: Any) -> None:
        pass

    if worker:
        configure_logging("DEBUG")
        config = uvicorn.Config(app, log_config=None)
    else:

        def factory() -> Any:
            configure_logging("DEBUG")
            return app

        config = uvicorn.Config(factory, factory=True)
    config.load()
    return config


def request_cycle(
    target: str = "/health/live?access_token=UVICORN_PRIVATE_TOKEN",
) -> RequestResponseCycle:
    path, _, query = target.partition("?")
    connection = h11.Connection(h11.SERVER)
    connection.receive_data(f"GET {target} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    connection.next_event()
    transport = Mock()
    return RequestResponseCycle(
        scope={
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "scheme": "http",
            "raw_path": path.encode(),
            "root_path": "",
            "server": ("127.0.0.1", 8000),
            "method": "GET",
            "path": path,
            "query_string": query.encode(),
            "headers": [],
            "http_version": "1.1",
            "client": ("127.0.0.1", 1234),
        },
        conn=connection,
        transport=transport,
        flow=FlowControl(transport),
        logger=logging.getLogger("uvicorn.error"),
        access_logger=logging.getLogger("uvicorn.access"),
        access_log=True,
        default_headers=[],
        message_event=asyncio.Event(),
        on_response=lambda: None,
    )


@pytest.mark.parametrize("worker", [False, True], ids=["api-default-factory", "worker-health"])
@pytest.mark.parametrize(
    ("target", "path"),
    [
        ("/health/live?access_token=UVICORN_PRIVATE_TOKEN", "/health/live"),
        ("http://USER_PRIVATE:PASS_PRIVATE@host/health/live?token=QUERY_PRIVATE", "/health/live"),
        ("//USER_PRIVATE:PASS_PRIVATE@host/health/live?token=QUERY_PRIVATE", "/health/live"),
        ("http://USER_PRIVATE:PASS_PRIVATE@[broken/health/live?token=QUERY_PRIVATE", "[invalid]"),
    ],
    ids=["path", "absolute", "network-path", "invalid-authority"],
)
async def test_uvicorn_access_keeps_request_metadata_without_query(
    worker: bool,
    process_output: io.StringIO,
    target: str,
    path: str,
) -> None:
    configure_server(worker, process_output)
    await request_cycle(target).send({"type": "http.response.start", "status": 200, "headers": []})
    output = process_output.getvalue()
    assert "PRIVATE" not in output
    records = [json.loads(line) for line in output.splitlines()]
    access = next(record for record in records if record["logger"] == "uvicorn.access")
    assert access["http.request.method"] == "GET"
    assert access["url.path"] == path
    assert access["http.response.status_code"] == 200
    assert access["client.address"] == "127.0.0.1:1234"


@pytest.mark.parametrize("worker", [False, True], ids=["api-default-factory", "worker-health"])
async def test_uvicorn_exception_keeps_types_and_frames_without_values(
    worker: bool,
    process_output: io.StringIO,
) -> None:
    configure_server(worker, process_output)

    async def failing_app(_scope: Any, _receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise ValueError("BODY_PRIVATE_PASSWORD")

    await request_cycle().run_asgi(failing_app)
    output = process_output.getvalue()
    assert "PRIVATE_" not in output
    error = next(json.loads(line) for line in output.splitlines() if '"exception"' in line)
    assert "ValueError" in error["exception"]
    assert "failing_app" in error["exception"]
    assert "raise ValueError" not in error["exception"]


async def test_uvicorn_lifespan_preformatted_failure_does_not_leak(
    process_output: io.StringIO,
) -> None:
    lifespan = LifespanOn(configure_server(False, process_output))
    await lifespan.send({"type": "lifespan.startup.failed", "message": "BODY_PRIVATE_PASSWORD"})
    assert "BODY_PRIVATE_PASSWORD" not in process_output.getvalue()
    assert json.loads(process_output.getvalue())["level"] == "ERROR"


async def test_uvicorn_invalid_return_value_does_not_leak(process_output: io.StringIO) -> None:
    configure_server(False, process_output)

    async def invalid_app(_scope: Any, _receive: Any, _send: Any) -> Any:
        return "BODY_PRIVATE_PASSWORD"

    await request_cycle().run_asgi(invalid_app)
    assert "BODY_PRIVATE_PASSWORD" not in process_output.getvalue()
    assert json.loads(process_output.getvalue())["level"] == "ERROR"


async def test_httpcore2_debug_trace_does_not_log_authorization(
    process_output: io.StringIO,
) -> None:
    sys.stdout = process_output
    configure_logging("DEBUG")
    async with Trace(
        "send_request_headers",
        logging.getLogger("httpcore2.http11"),
        kwargs={"request": [(b"authorization", b"DEBUG_PRIVATE_TOKEN")]},
    ):
        pass
    assert "DEBUG_PRIVATE_TOKEN" not in process_output.getvalue()


@pytest.mark.parametrize("name", ["aiormq.channel", "aio_pika.tools", "pgqueuer", "faststream"])
@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO, logging.ERROR])
def test_library_rendered_messages_and_extras_are_not_trusted(
    name: str,
    level: int,
    process_output: io.StringIO,
) -> None:
    sys.stdout = process_output
    configure_logging("DEBUG")
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.log(
        level,
        "callback failure %r",
        ValueError("BODY_PRIVATE_PASSWORD"),
        extra={"payload": "EXTRA_PRIVATE_PASSWORD"},
    )
    output = process_output.getvalue()
    assert "PRIVATE_PASSWORD" not in output
    assert json.loads(output)["logger"] == name
    assert "ValueError" in json.loads(output)["exception"]
