import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from fast_ddd.errors import DomainError, ErrorKind
from fast_ddd.serialization import to_json
from fast_ddd_devtools.error_catalog import build_catalog, main
from fast_ddd_port.models import MessageModel, RequestModel, ResponseModel
from fast_ddd_port.problems import domain_problem, install_problem_handlers
from fast_ddd_port.settings import KernelSettings, load_settings


def test_settings_fail_without_jwt_claim_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "svc")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
    monkeypatch.setenv("JWT__ISSUER", "iss")
    monkeypatch.setenv("JWT__AUDIENCE", "aud")
    monkeypatch.setenv("JWT__JWKS_URL", "https://jwks")

    with pytest.raises(ValidationError) as error:
        load_settings(KernelSettings)

    missing = {e["loc"][-1] for e in error.value.errors() if e["type"] == "missing"}
    assert missing == {
        "user_id_claim",
        "organization_id_claim",
        "permissions_claim",
        "permissions_format",
    }


def test_catalog_lists_kernel_domain_and_aggregate_codes(tmp_path: Path) -> None:
    output = tmp_path / "errors.json"

    assert main(["tests.adapter.models", "--output", str(output)]) == 0

    entries: dict[str, dict[str, Any]] = {e["code"]: e for e in json.loads(output.read_text())}
    assert entries["auth.token_expired"]["status"] == 401
    assert entries["kernel_test.order.already_voided"]["params"] == ["orderId"]
    assert entries["kernel_test.order.not_found"]["status"] == 404
    assert [e["code"] for e in build_catalog()] == sorted(entries)


@dataclass
class NumberedFieldInvalid(DomainError):
    code: ClassVar[str] = "kernel_test.numbered_field_invalid"
    kind: ClassVar[ErrorKind] = ErrorKind.INVALID
    message: ClassVar[str] = "Invalid {line1A} for {postalCode}"

    line_1a: str
    postal_code: str


def test_error_params_catalog_and_wire_aliases_share_canonical_names() -> None:
    error = NumberedFieldInvalid("bad", "123")
    expected = {"line1A": "bad", "postalCode": "123"}
    entry = next(entry for entry in build_catalog() if entry["code"] == error.code)
    assert entry["params"] == list(expected)
    assert error.params() == expected
    assert to_json(error, camel_case=True) == expected
    assert error.detail() == "Invalid bad for 123"
    assert domain_problem(error).params == expected

    class Request(RequestModel):
        line_1a: str
        postal_code: str

    class Message(MessageModel):
        line_1a: str
        postal_code: str

    class Response(ResponseModel):
        line_1a: str
        postal_code: str

    assert Request.model_validate(expected).line_1a == "bad"
    assert Message.model_validate(expected).line_1a == "bad"
    assert Response(line_1a="bad", postal_code="123").model_dump() == expected


async def test_numbered_error_field_returns_invalid_problem_over_http() -> None:
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/numbered")
    async def reject_numbered_field() -> None:
        raise NumberedFieldInvalid("bad", "123")

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/numbered")
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["params"] == {"line1A": "bad", "postalCode": "123"}
    assert response.json()["detail"] == "Invalid bad for 123"
