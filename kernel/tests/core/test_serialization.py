from dataclasses import dataclass, make_dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

import pendulum
import pytest

from fast_ddd.serialization import to_json


class State(StrEnum):
    READY = "ready"


@dataclass
class Address:
    street_name: str
    internal_field: str = "nested"


@dataclass
class Payload:
    customer_id: UUID
    shipping_address: Address
    custom_labels: dict[str, str]
    total_amount: Decimal
    occurred_at: pendulum.DateTime
    state: State
    internal_field: str


def test_dataclass_wire_fields_preserve_nested_maps_and_exclude_only_root_fields() -> None:
    value = Payload(
        UUID(int=1),
        Address("Main"),
        {"partner_key": "x", "en-US": "y"},
        Decimal("12345678901234567890.50"),
        pendulum.datetime(2026, 1, 1, 8, tz="Asia/Taipei"),
        State.READY,
        "private",
    )
    assert to_json(value, camel_case=True, exclude_fields=frozenset({"internal_field"})) == {
        "customerId": str(UUID(int=1)),
        "shippingAddress": {"streetName": "Main", "internalField": "nested"},
        "customLabels": {"partner_key": "x", "en-US": "y"},
        "totalAmount": "12345678901234567890.50",
        "occurredAt": "2026-01-01T00:00:00.000Z",
        "state": "ready",
    }
    internal = to_json(value)
    assert isinstance(internal, dict)
    assert internal["customer_id"] == str(UUID(int=1))
    assert internal["shipping_address"] == {"street_name": "Main", "internal_field": "nested"}
    assert internal["internal_field"] == "private"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("line_1a", "line1A"),
        ("version_2_id", "version2Id"),
        ("alreadyCamelCase", "alreadyCamelCase"),
        ("line1a", "line1A"),
        ("postal_code", "postalCode"),
    ],
)
def test_canonical_camel_case_handles_numeric_and_existing_camel_fields(
    name: str, expected: str
) -> None:
    record = make_dataclass("WireRecord", [(name, str)])("value")
    assert to_json(record, camel_case=True) == {expected: "value"}
