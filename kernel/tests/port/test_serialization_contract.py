from dataclasses import dataclass

from fast_ddd.serialization import to_json
from fast_ddd_port.models import MessageModel


@dataclass
class NumberedFields:
    line_1a: str
    ipv4_address: str
    customer_id: str


class IncomingFields(MessageModel):
    line_1a: str
    ipv4_address: str
    customer_id: str


def test_dataclass_producer_matches_message_aliases_with_numbered_fields() -> None:
    wire = to_json(NumberedFields("one", "127.0.0.1", "customer"), camel_case=True)
    received = IncomingFields.model_validate(wire)
    assert received.line_1a == "one"
    assert received.ipv4_address == "127.0.0.1"
    assert received.customer_id == "customer"
    assert received.model_dump(mode="json", by_alias=True) == wire
