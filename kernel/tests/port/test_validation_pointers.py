import re
from typing import Any, cast
from urllib.parse import unquote

import httpx2
import pytest
from fastapi import FastAPI

from fast_ddd_port.models import RequestModel, Timestamp
from fast_ddd_port.problems import install_problem_handlers


class Entries(RequestModel):
    entries: dict[str, list[int]]


class TimestampBody(RequestModel):
    payload_timestamp: Timestamp


def resolve_fragment(document: Any, fragment: str) -> Any:
    assert fragment.startswith("#")
    pointer = unquote(fragment[1:], encoding="utf-8", errors="strict")
    if pointer == "":
        return document
    assert pointer.startswith("/")
    value = document
    for encoded in pointer[1:].split("/"):
        assert not re.search(r"~(?:[^01]|$)", encoded)
        token = encoded.replace("~1", "/").replace("~0", "~")
        value = cast(list[Any], value)[int(token)] if isinstance(value, list) else value[token]
    return value


@pytest.mark.parametrize(
    ("key", "fragment"),
    [
        ("plain", "plain"),
        ("a/b~c", "a~1b~0c"),
        ("~1", "~01"),
        ("a%2Fb", "a%252Fb"),
        ("# key", "%23%20key"),
        ("?", "%3F"),
        ("%23", "%2523"),
        ("#", "%23"),
        ("中文", "%E4%B8%AD%E6%96%87"),
        ("", ""),
        ("0", "0"),
        ("partner_key", "partner_key"),
    ],
)
async def test_validation_pointer_resolves_original_map_key_and_array_index(
    key: str, fragment: str
) -> None:
    app = FastAPI()
    install_problem_handlers(app)

    @app.post("/entries")
    async def submit(_value: Entries) -> None:
        raise AssertionError("invalid input reached handler")

    body = {"entries": {key: [1, "invalid"]}}
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/entries", json=body)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    errors = response.json()["errors"]
    assert len(errors) == 1
    pointer = errors[0]["pointer"]
    assert resolve_fragment(body, pointer) == "invalid"
    assert pointer == f"#/entries/{fragment}/1"


async def test_validation_pointer_for_body_root_resolves_original_document() -> None:
    app = FastAPI()
    install_problem_handlers(app)

    @app.post("/entries")
    async def submit(_value: Entries) -> None:
        raise AssertionError("invalid input reached handler")

    body: list[int] = []
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/entries", json=body)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    pointer = response.json()["errors"][0]["pointer"]
    assert resolve_fragment(body, pointer) == body
    assert pointer == "#"


async def test_missing_leaf_pointer_preserves_declared_alias_and_existing_parent() -> None:
    app = FastAPI()
    install_problem_handlers(app)

    @app.post("/timestamps")
    async def submit(_value: TimestampBody) -> None:
        raise AssertionError("invalid input reached handler")

    body: dict[str, Any] = {}
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/timestamps", json=body)
    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert error["code"] == "validation.missing"
    assert error["pointer"] == "#/payloadTimestamp"
    parent_fragment, missing_name = error["pointer"].rsplit("/", 1)
    assert missing_name not in resolve_fragment(body, parent_fragment)


@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"])
async def test_out_of_range_timestamp_returns_http_validation_problem(timestamp: str) -> None:
    app = FastAPI()
    install_problem_handlers(app)

    @app.post("/timestamps")
    async def submit(_value: TimestampBody) -> None:
        raise AssertionError("invalid input reached handler")

    body = {"payloadTimestamp": timestamp}
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/timestamps", json=body)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["code"] == "validation.failed"
    assert len(problem["errors"]) == 1
    assert problem["errors"][0]["pointer"] == "#/payloadTimestamp"
    assert resolve_fragment(body, problem["errors"][0]["pointer"]) == timestamp
