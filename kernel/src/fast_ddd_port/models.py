from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

import pendulum
from pydantic import (
    MISSING,
    BaseModel,
    ConfigDict,
    PlainSerializer,
    PlainValidator,
    WithJsonSchema,
)

from fast_ddd.serialization import format_datetime, to_camel
from fast_ddd_adapter.commands import UNSET, Unset


class RequestModel(BaseModel):
    """HTTP request body/query: camelCase only, unknown fields rejected."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
    )


class ResponseModel(BaseModel):
    """Response: camelCase on the wire, constructed by field name in ``from_domain``."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
        frozen=True,
    )


class MessageModel(BaseModel):
    """Incoming MQ message: camelCase, unknown fields ignored for forward compatibility."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=False,
        extra="ignore",
        frozen=True,
    )


def _to_pendulum(value: Any) -> pendulum.DateTime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise ValueError("expected an RFC 3339 date-time string")
    if value.tzinfo is None:
        raise ValueError("a time zone offset is required")
    try:
        return pendulum.instance(value).in_timezone("UTC")
    except OverflowError as error:
        raise ValueError("date-time is outside the UTC range") from error


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        raise ValueError("decimals must be sent as strings to keep their precision")
    try:
        number = Decimal(value)
    except ArithmeticError as error:
        raise ValueError("not a decimal number") from error
    if not number.is_finite():
        raise ValueError("not a finite decimal number")
    return number


Timestamp = Annotated[
    pendulum.DateTime,
    PlainValidator(_to_pendulum),
    PlainSerializer(format_datetime, return_type=str),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]

DecimalStr = Annotated[
    Decimal,
    PlainValidator(_to_decimal),
    PlainSerializer(str, return_type=str),
    WithJsonSchema({"type": "string", "format": "decimal"}),
]


def etag_of(version: int) -> str:
    return f'"{version}"'


def unset_if_missing[T](value: T | MISSING) -> T | Unset:
    """PATCH: a field the client did not send (``MISSING``) becomes the command's ``UNSET``."""
    return UNSET if value is MISSING else value


def convert_unless_missing[T, R](value: T | MISSING, convert: Callable[[T], R]) -> R | Unset:
    """``unset_if_missing`` for fields that also need converting, e.g. a body to a value object."""
    return UNSET if value is MISSING else convert(value)
