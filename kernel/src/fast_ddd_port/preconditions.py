import re
from http import HTTPStatus
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, Header

from fast_ddd_port.problems import PROBLEM_JSON, HttpProblem, Problem

_STRONG_ETAG = re.compile(r'^"(\d+)"$')


def parse_if_match(value: str | None) -> int:
    if value is None or not value.strip():
        raise HttpProblem("concurrency.precondition_required")
    match = _STRONG_ETAG.fullmatch(value.strip())
    if match is None:
        raise HttpProblem("concurrency.invalid_if_match", detail=f"unsupported If-Match: {value}")
    try:
        return int(match.group(1))
    except ValueError as error:
        raise HttpProblem(
            "concurrency.invalid_if_match", detail=f"unsupported If-Match: {value}"
        ) from error


def parse_etag(value: str) -> int:
    """Per-item ``etag`` in a batch body; the same format as the If-Match header."""
    return parse_if_match(value)


def _if_match(if_match: Annotated[str | None, Header(alias="If-Match")] = None) -> int:
    return parse_if_match(if_match)


ExpectedVersion = Annotated[int, Depends(_if_match)]


def mark_if_match_required(schema: dict[str, Any]) -> dict[str, Any]:
    """The header is optional in Python (so a missing one is 428, not 422) but required in docs."""
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            for parameter in operation.get("parameters", []):
                if parameter.get("in") == "header" and parameter.get("name") == "If-Match":
                    parameter["required"] = True
    return schema


def _install_http_responses(schema: dict[str, Any]) -> dict[str, Any]:
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    problem = Problem.model_json_schema(
        mode="serialization", ref_template="#/components/schemas/{model}"
    )
    components.update(problem.pop("$defs", {}))
    components["Problem"] = problem
    for path in schema.get("paths", {}).values():
        for raw_operation in path.values():
            if not isinstance(raw_operation, dict) or "responses" not in raw_operation:
                continue
            operation = cast(dict[str, Any], raw_operation)
            responses: dict[str, Any] = operation["responses"]
            statuses = {"400", "401", "403", "404", "405", "409", "422", "500", "503"}
            if "requestBody" in operation:
                statuses.add("415")
            if any(p.get("name") == "If-Match" for p in operation.get("parameters", [])):
                statuses.update({"412", "428"})
            for status in sorted(statuses):
                responses[status] = {
                    "description": HTTPStatus(int(status)).phrase,
                    "content": {PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/Problem"}}},
                }
            responses.setdefault(
                "default",
                {
                    "description": "Problem response",
                    "content": {PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/Problem"}}},
                },
            )
            for status, response in responses.items():
                headers = response.setdefault("headers", {})
                headers["X-Trace-Id"] = {"schema": {"type": "string"}}
                if status == "401":
                    headers["WWW-Authenticate"] = {"schema": {"type": "string"}}
                if status == "405":
                    headers["Allow"] = {"schema": {"type": "string"}}
                if status.startswith("2"):
                    body = response.get("content", {}).get("application/json", {}).get("schema", {})
                    model = components.get(body.get("$ref", "").rsplit("/", 1)[-1], body)
                    if "etag" in model.get("properties", {}):
                        headers["ETag"] = {"schema": {"type": "string", "pattern": r'^"\d+"$'}}
                    if status == "201":
                        headers["Location"] = {
                            "schema": {"type": "string", "format": "uri-reference"}
                        }
    return schema


def install_openapi_fixups(app: FastAPI) -> None:
    original = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = _install_http_responses(mark_if_match_required(original()))
        return app.openapi_schema

    app.openapi = openapi
