import re
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

import pendulum

from fast_ddd.serialization import format_datetime, to_camel

ERROR_CODE_PATTERN: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$")
ERROR_CODE_MAX_LENGTH = 63

type ParamValue = str | int | float | bool


class ErrorKind(StrEnum):
    INVALID = "invalid"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    PRECONDITION_FAILED = "precondition_failed"


def validate_error_code(code: str) -> str:
    if len(code) > ERROR_CODE_MAX_LENGTH or not ERROR_CODE_PATTERN.fullmatch(code):
        raise ValueError(f"invalid error code: {code!r}")
    return code


def humanize_class_name(name: str) -> str:
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()
    return words[:1].upper() + words[1:]


def _param_value(value: object) -> ParamValue:
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, pendulum.DateTime):
        return format_datetime(value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"unsupported error param type: {type(value).__name__}")


@dataclass
class DomainError(Exception):
    """Business rejection raised by the domain.

    Subclasses are dataclasses whose fields become the error ``params`` (camelCased).
    """

    code: ClassVar[str]
    kind: ClassVar[ErrorKind]
    message: ClassVar[str]

    registry: ClassVar[dict[str, type["DomainError"]]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        code = cls.__dict__.get("code")
        if not isinstance(code, str):
            return
        validate_error_code(code)
        existing = DomainError.registry.get(code)
        if existing is not None and existing is not cls:
            raise ValueError(f"duplicate error code {code!r}: {existing!r} and {cls!r}")
        DomainError.registry[code] = cls

    @property
    def error_code(self) -> str:
        return self.code

    @property
    def title(self) -> str:
        return humanize_class_name(type(self).__name__)

    def params(self) -> dict[str, ParamValue]:
        return {to_camel(f.name): _param_value(getattr(self, f.name)) for f in fields(self)}

    def detail(self) -> str:
        return self.message.format(**self.params())

    def __str__(self) -> str:
        return f"{self.error_code}: {self.detail()}"


@dataclass
class AggregateNotFound(DomainError):
    kind: ClassVar[ErrorKind] = ErrorKind.NOT_FOUND
    message: ClassVar[str] = "{aggregateType} {aggregateId} was not found"

    namespace: str
    aggregate_type: str
    aggregate_id: UUID

    @property
    def error_code(self) -> str:
        return f"{self.namespace}.not_found"

    @property
    def title(self) -> str:
        return f"{self.aggregate_type.replace('_', ' ').capitalize()} not found"

    def params(self) -> dict[str, ParamValue]:
        return {"aggregateType": self.aggregate_type, "aggregateId": str(self.aggregate_id)}


@dataclass
class AggregateAlreadyExists(DomainError):
    kind: ClassVar[ErrorKind] = ErrorKind.ALREADY_EXISTS
    message: ClassVar[str] = "{aggregateType} {aggregateId} already exists"

    namespace: str
    aggregate_type: str
    aggregate_id: UUID

    @property
    def error_code(self) -> str:
        return f"{self.namespace}.already_exists"

    @property
    def title(self) -> str:
        return f"{self.aggregate_type.replace('_', ' ').capitalize()} already exists"

    def params(self) -> dict[str, ParamValue]:
        return {"aggregateType": self.aggregate_type, "aggregateId": str(self.aggregate_id)}


@dataclass
class VersionMismatch(DomainError):
    code: ClassVar[str] = "concurrency.etag_mismatch"
    kind: ClassVar[ErrorKind] = ErrorKind.PRECONDITION_FAILED
    message: ClassVar[str] = "expected version {expectedVersion} but found {actualVersion}"

    expected_version: int
    actual_version: int


@dataclass
class LockConflict(DomainError):
    code: ClassVar[str] = "concurrency.lock_conflict"
    kind: ClassVar[ErrorKind] = ErrorKind.CONFLICT
    message: ClassVar[str] = "the resource is locked by another operation, retry later"
