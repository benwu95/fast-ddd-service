"""Contract tests for the wire format (camelCase, enums, UUIDs, RFC 3339, decimals)."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID, uuid4

import pendulum
import pytest
from pydantic import MISSING, Field, TypeAdapter, ValidationError

from fast_ddd_adapter.commands import UNSET
from fast_ddd_port.models import (
    DecimalStr,
    MessageModel,
    RequestModel,
    ResponseModel,
    Timestamp,
    convert_unless_missing,
    etag_of,
    unset_if_missing,
)


class Color(StrEnum):
    DARK_RED = "dark_red"


class Inner(RequestModel):
    property_a: str


class CreateRequest(RequestModel):
    owner_id: UUID
    color: Color
    inner: Inner
    due_at: Timestamp
    price: Annotated[DecimalStr, Field(ge=0, decimal_places=2)]


class InnerResponse(ResponseModel):
    property_a: str


class ThingResponse(ResponseModel):
    owner_id: UUID
    color: Color
    inner: InnerResponse
    created_at: Timestamp
    price: DecimalStr


class Incoming(MessageModel):
    order_id: UUID


def body(**overrides: Any) -> dict[str, Any]:
    return {
        "ownerId": str(uuid4()),
        "color": "dark_red",
        "inner": {"propertyA": "a"},
        "dueAt": "2026-10-17T10:00:00+08:00",
        "price": "10.50",
        **overrides,
    }


def error_types(data: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as caught:
        CreateRequest.model_validate(data)
    return [error["type"] for error in caught.value.errors()]


def test_request_accepts_camel_case_and_converts_types() -> None:
    request = CreateRequest.model_validate(body())

    assert request.color is Color.DARK_RED
    assert request.inner.property_a == "a"
    assert request.due_at == pendulum.datetime(2026, 10, 17, 2, tz="UTC")
    assert isinstance(request.due_at, pendulum.DateTime)
    assert request.price == Decimal("10.50")


def test_request_rejects_snake_case_unknown_fields_and_bad_enums() -> None:
    data = body()
    data["owner_id"] = data.pop("ownerId")
    assert error_types(data) == ["missing", "extra_forbidden"]
    assert error_types(body(status="voided")) == ["extra_forbidden"]
    assert error_types(body(color="DARK_RED")) == ["enum"]


@pytest.mark.parametrize(
    "due_at", ["2026-10-17T10:00:00", 1760000000, "yesterday", "2026-10-17T10:00:00+0800x"]
)
def test_timestamps_need_an_offset_and_a_string(due_at: object) -> None:
    assert error_types(body(dueAt=due_at)) == ["value_error"]


@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"])
@pytest.mark.parametrize("as_datetime", [False, True])
def test_timestamps_outside_utc_range_are_validation_errors(
    timestamp: str, as_datetime: bool
) -> None:
    value = datetime.fromisoformat(timestamp) if as_datetime else timestamp
    with pytest.raises(ValidationError) as caught:
        TypeAdapter(Timestamp).validate_python(value)
    assert caught.value.errors()[0]["type"] == "value_error"


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("0001-01-01T14:00:00+14:00", "0001-01-01T00:00:00+00:00"),
        ("9999-12-31T09:59:59.999999-14:00", "9999-12-31T23:59:59.999999+00:00"),
    ],
)
def test_timestamps_at_valid_utc_boundaries(timestamp: str, expected: str) -> None:
    value = TypeAdapter(Timestamp).validate_python(timestamp)
    assert isinstance(value, pendulum.DateTime)
    assert value.isoformat() == expected


@pytest.mark.parametrize("price", [10.5, 10, "NaN", "Infinity", "-sNaN", "ten"])
def test_decimals_must_be_finite_strings(price: object) -> None:
    assert error_types(body(price=price)) == ["value_error"]


def test_decimal_constraints_still_apply() -> None:
    assert error_types(body(price="-1")) == ["greater_than_equal"]
    assert error_types(body(price="1.234")) == ["decimal_max_places"]


def test_large_decimal_strings_keep_their_precision() -> None:
    request = CreateRequest.model_validate(body(price="12345678901234567.89"))
    assert request.price == Decimal("12345678901234567.89")


def test_response_is_built_by_field_name_and_dumped_in_camel_case() -> None:
    owner_id = uuid4()
    response = ThingResponse(
        owner_id=owner_id,
        color=Color.DARK_RED,
        inner=InnerResponse(property_a="a"),
        created_at=pendulum.datetime(2026, 10, 17, 10, 0, 0, 123456, tz="Asia/Taipei"),
        price=Decimal("10.50"),
    )

    assert response.model_dump(mode="json") == {
        "ownerId": str(owner_id),
        "color": "dark_red",
        "inner": {"propertyA": "a"},
        "createdAt": "2026-10-17T02:00:00.123Z",
        "price": "10.50",
    }


def test_schema_types_for_generated_clients() -> None:
    properties = ThingResponse.model_json_schema()["properties"]

    assert properties["createdAt"] | {"title": ""} == {
        "type": "string",
        "format": "date-time",
        "title": "",
    }
    assert properties["price"] | {"title": ""} == {
        "type": "string",
        "format": "decimal",
        "title": "",
    }
    assert properties["ownerId"]["format"] == "uuid"


def test_messages_ignore_unknown_fields_but_only_accept_camel_case() -> None:
    order_id = uuid4()
    assert Incoming.model_validate({"orderId": str(order_id), "added": 1}).order_id == order_id
    with pytest.raises(ValidationError):
        Incoming.model_validate({"order_id": str(order_id)})


def test_etag_is_a_strong_quoted_version() -> None:
    assert etag_of(3) == '"3"'


class PatchRequest(RequestModel):
    name: Annotated[str, Field(min_length=1)] | MISSING = MISSING
    note: str | MISSING | None = MISSING


def test_patch_distinguishes_not_sent_from_null() -> None:
    patch = PatchRequest.model_validate({"note": None})

    assert unset_if_missing(patch.name) is UNSET
    assert unset_if_missing(patch.note) is None
    assert convert_unless_missing(patch.name, len) is UNSET
    assert convert_unless_missing(PatchRequest.model_validate({"name": "abc"}).name, len) == 3
    with pytest.raises(ValidationError) as caught:
        PatchRequest.model_validate({"name": None})
    assert caught.value.errors()[0]["type"] == "string_type"
    assert "required" not in PatchRequest.model_json_schema()
