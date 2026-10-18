import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from fast_ddd.context import current_trace_id
from fast_ddd.errors import DomainError, ErrorKind, ParamValue
from fast_ddd.serialization import to_camel
from fast_ddd_adapter.controller import EventHandlerFailedError, UnexpectedFailure

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"

KIND_STATUS: Mapping[ErrorKind, int] = {
    ErrorKind.INVALID: 422,
    ErrorKind.CONFLICT: 409,
    ErrorKind.NOT_FOUND: 404,
    ErrorKind.ALREADY_EXISTS: 409,
    ErrorKind.PRECONDITION_FAILED: 412,
}

# code -> (status, English title); the source for the error catalog as well.
KERNEL_CODES: Mapping[str, tuple[int, str]] = {
    "request.malformed_json": (400, "Malformed JSON"),
    "request.route_not_found": (404, "Route not found"),
    "request.method_not_allowed": (405, "Method not allowed"),
    "request.unsupported_media_type": (415, "Unsupported media type"),
    "request.content_too_large": (413, "Content too large"),
    "validation.failed": (422, "Validation failed"),
    "auth.unauthenticated": (401, "Authentication required"),
    "auth.token_invalid": (401, "Invalid token"),
    "auth.token_expired": (401, "Token expired"),
    "auth.permission_denied": (403, "Permission denied"),
    "concurrency.etag_mismatch": (412, "The resource was changed by someone else"),
    "concurrency.precondition_required": (428, "If-Match header is required"),
    "concurrency.invalid_if_match": (400, "If-Match must be a single strong ETag"),
    "concurrency.lock_conflict": (409, "The resource is busy, retry later"),
    "rate_limit.exceeded": (429, "Too many requests"),
    "server.internal_error": (500, "Internal server error"),
    "server.unavailable": (503, "Service unavailable"),
}

VALIDATION_CODES = frozenset(
    {
        "missing",
        "extra_forbidden",
        "string_type",
        "string_too_short",
        "string_too_long",
        "string_pattern_mismatch",
        "int_type",
        "int_parsing",
        "float_parsing",
        "bool_parsing",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "too_short",
        "too_long",
        "enum",
        "literal_error",
        "uuid_parsing",
        "uuid_type",
        "list_type",
        "dict_type",
        "model_type",
        "duplicate_id",
    }
)
_PRESENTED_CTX = frozenset({"expected", "error"})


class FieldError(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, validate_by_name=True, serialize_by_alias=True
    )

    pointer: str | None = None
    parameter: str | None = None
    code: str
    params: dict[str, ParamValue] = Field(default_factory=dict[str, ParamValue])
    detail: str


class Problem(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, validate_by_name=True, serialize_by_alias=True
    )

    type: str
    title: str
    status: int
    detail: str | None = None
    code: str
    params: dict[str, ParamValue] = Field(default_factory=dict[str, ParamValue])
    errors: list[FieldError] | None = None
    trace_id: str | None = None


@dataclass
class HttpProblem(Exception):
    """A kernel-level HTTP error (authentication, preconditions, request shape)."""

    code: str
    detail: str | None = None
    headers: dict[str, str] = field(default_factory=dict[str, str])
    errors: list[FieldError] | None = None

    @property
    def status(self) -> int:
        return KERNEL_CODES[self.code][0]


def make_problem(
    *,
    code: str,
    status: int,
    title: str,
    detail: str | None = None,
    params: Mapping[str, ParamValue] | None = None,
    errors: list[FieldError] | None = None,
) -> Problem:
    return Problem(
        type=f"/problems/{code}",
        title=title,
        status=status,
        detail=detail,
        code=code,
        params=dict(params or {}),
        errors=errors,
        trace_id=current_trace_id(),
    )


def kernel_problem(code: str, detail: str | None = None, **params: ParamValue) -> Problem:
    status, title = KERNEL_CODES[code]
    return make_problem(code=code, status=status, title=title, detail=detail, params=params)


def domain_problem(error: DomainError) -> Problem:
    kernel = KERNEL_CODES.get(error.error_code)
    title = kernel[1] if kernel else error.title
    return make_problem(
        code=error.error_code,
        status=KIND_STATUS[error.kind],
        title=title,
        detail=error.detail(),
        params=error.params(),
    )


def outcome_problem(outcome: DomainError | UnexpectedFailure) -> Problem:
    if isinstance(outcome, DomainError):
        return domain_problem(outcome)
    return kernel_problem("server.internal_error")


def problem_response(problem: Problem, headers: Mapping[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(mode="json", by_alias=True, exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_JSON,
        headers=dict(headers or {}),
    )


def _json_pointer(location: Sequence[int | str]) -> str:
    pointer = "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in location)
    return "#" + quote(pointer, safe="/~")


def field_errors(raw_errors: Sequence[Any]) -> list[FieldError]:
    result: list[FieldError] = []
    for raw in raw_errors:
        error = cast(Mapping[str, Any], raw)
        location = cast(Sequence[int | str], error.get("loc", ()))
        error_type = str(error.get("type", ""))
        code = (
            f"validation.{error_type}" if error_type in VALIDATION_CODES else "validation.invalid"
        )
        ctx = cast(Mapping[str, Any], error.get("ctx") or {})
        params: dict[str, ParamValue] = {
            to_camel(key): value
            for key, value in ctx.items()
            if key not in _PRESENTED_CTX and isinstance(value, bool | int | float | str)
        }
        source, *path = location or ("body",)
        message = str(error.get("msg", ""))
        if source == "body":
            result.append(
                FieldError(pointer=_json_pointer(path), code=code, params=params, detail=message)
            )
        else:
            name = str(path[0]) if path else str(source)
            result.append(FieldError(parameter=name, code=code, params=params, detail=message))
    return result


def duplicate_id_problem(indices: Sequence[int]) -> HttpProblem:
    return HttpProblem(
        code="validation.failed",
        errors=[
            FieldError(
                pointer=f"#/items/{index}/id",
                code="validation.duplicate_id",
                detail="The same id appears more than once in this batch",
            )
            for index in indices
        ],
    )


async def _on_domain_error(_: Request, error: Exception) -> JSONResponse:
    return problem_response(domain_problem(cast(DomainError, error)))


async def _on_http_problem(_: Request, error: Exception) -> JSONResponse:
    problem = cast(HttpProblem, error)
    body = kernel_problem(problem.code, problem.detail)
    if problem.errors is not None:
        body = body.model_copy(update={"errors": problem.errors})
    return problem_response(body, problem.headers)


async def _on_validation_error(_: Request, error: Exception) -> JSONResponse:
    raw = cast(RequestValidationError, error).errors()
    if any(cast(Mapping[str, Any], e).get("type") == "json_invalid" for e in raw):
        return problem_response(kernel_problem("request.malformed_json"))
    problem = kernel_problem("validation.failed").model_copy(update={"errors": field_errors(raw)})
    return problem_response(problem)


async def _on_starlette_http(_: Request, error: Exception) -> JSONResponse:
    http_error = cast(StarletteHTTPException, error)
    status = http_error.status_code
    code = {404: "request.route_not_found", 405: "request.method_not_allowed"}.get(status)
    if code is None:
        logger.warning("unmapped HTTP exception %s", status)
        code = "server.internal_error"
    return problem_response(
        kernel_problem(code), http_error.headers if status in (404, 405) else None
    )


async def _on_handler_failed(_: Request, error: Exception) -> JSONResponse:
    logger.error("event handler failed", exc_info=error)
    return problem_response(kernel_problem("server.internal_error"))


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _on_domain_error)
    app.add_exception_handler(HttpProblem, _on_http_problem)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(StarletteHTTPException, _on_starlette_http)
    app.add_exception_handler(EventHandlerFailedError, _on_handler_failed)
