from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final
from uuid import UUID


class ContextNotSetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class User:
    id: str
    name: str | None = None


class _Unset:
    pass


_UNSET: Final = _Unset()

_user: ContextVar[User | _Unset] = ContextVar("fast_ddd_user", default=_UNSET)
_organization_id: ContextVar[UUID | _Unset | None] = ContextVar(
    "fast_ddd_organization_id", default=_UNSET
)
_tenant_exempt: ContextVar[bool] = ContextVar("fast_ddd_tenant_exempt", default=False)
_trace_id: ContextVar[str | None] = ContextVar("fast_ddd_trace_id", default=None)
_parent_event_id: ContextVar[UUID | None] = ContextVar("fast_ddd_parent_event_id", default=None)


def current_user() -> User:
    user = _user.get()
    if isinstance(user, _Unset):
        raise ContextNotSetError("user is not set; run inside a unit of work")
    return user


def current_organization_id() -> UUID | None:
    organization_id = _organization_id.get()
    if isinstance(organization_id, _Unset):
        raise ContextNotSetError("organization is not set; run inside a unit of work")
    return organization_id


def is_tenant_exempt() -> bool:
    return _tenant_exempt.get()


def current_trace_id() -> str | None:
    return _trace_id.get()


def current_parent_event_id() -> UUID | None:
    return _parent_event_id.get()


@contextmanager
def unit_of_work_context(
    *,
    user: User,
    organization_id: UUID | None,
    trace_id: str | None = None,
    parent_event_id: UUID | None = None,
) -> Generator[None]:
    tokens = (
        _user.set(user),
        _organization_id.set(organization_id),
        _tenant_exempt.set(False),
        _trace_id.set(trace_id),
        _parent_event_id.set(parent_event_id),
    )
    try:
        yield
    finally:
        _parent_event_id.reset(tokens[4])
        _trace_id.reset(tokens[3])
        _tenant_exempt.reset(tokens[2])
        _organization_id.reset(tokens[1])
        _user.reset(tokens[0])


@contextmanager
def event_scope(*, event_id: UUID, organization_id: UUID | None) -> Generator[None]:
    tokens = (
        _parent_event_id.set(event_id),
        _organization_id.set(organization_id),
        _tenant_exempt.set(False),
    )
    try:
        yield
    finally:
        _tenant_exempt.reset(tokens[2])
        _organization_id.reset(tokens[1])
        _parent_event_id.reset(tokens[0])


@contextmanager
def tenant_exemption() -> Generator[None]:
    token = _tenant_exempt.set(True)
    try:
        yield
    finally:
        _tenant_exempt.reset(token)


@contextmanager
def trace_scope(trace_id: str | None) -> Generator[None]:
    token = _trace_id.set(trace_id)
    try:
        yield
    finally:
        _trace_id.reset(token)
