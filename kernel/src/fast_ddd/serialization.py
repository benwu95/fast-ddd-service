import dataclasses
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast
from uuid import UUID

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None


def format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("naive datetime cannot be serialized")
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_camel(name: str) -> str:
    if re.match(r"^[a-z]+[A-Za-z0-9]*$", name) and not re.search(r"\d[a-z]", name):
        return name
    pascal = re.sub(r"([0-9A-Za-z])_(?=[0-9A-Z])", r"\1", name.title())
    return re.sub(r"(^_*[A-Z])", lambda match: match.group(1).lower(), pascal)


def to_json(
    value: object, *, camel_case: bool = False, exclude_fields: frozenset[str] = frozenset()
) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return to_json(cast(object, value.value), camel_case=camel_case)
    if isinstance(value, datetime):
        return format_datetime(value)
    if isinstance(value, UUID | Decimal):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            (to_camel(field.name) if camel_case else field.name): to_json(
                getattr(value, field.name), camel_case=camel_case
            )
            for field in dataclasses.fields(value)
            if field.name not in exclude_fields
        }
    if isinstance(value, Mapping):
        mapping = cast(Mapping[Any, Any], value)
        return {str(k): to_json(v, camel_case=camel_case) for k, v in mapping.items()}
    if isinstance(value, list | tuple | set | frozenset):
        items = cast(list[Any] | tuple[Any, ...] | set[Any] | frozenset[Any], value)
        return [to_json(item, camel_case=camel_case) for item in items]
    raise TypeError(f"cannot serialize {type(value).__name__}")
