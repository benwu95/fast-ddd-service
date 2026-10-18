import re
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.errors import AggregateAlreadyExists, DomainError, LockConflict

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
LOCK_NOT_AVAILABLE = "55P03"
DEADLOCK_DETECTED = "40P01"

_KEY_ID = re.compile(r"\(id\)=\(([0-9a-fA-F-]{36})\)")

type ConstraintErrorFactory = Callable[[], DomainError]

_primary_keys: dict[str, type[AggregateRoot]] = {}
_constraint_errors: dict[str, ConstraintErrorFactory] = {}


def register_primary_key(constraint_name: str, aggregate_class: type[AggregateRoot]) -> None:
    _primary_keys[constraint_name] = aggregate_class


def register_constraint_error(constraint_name: str, factory: ConstraintErrorFactory) -> None:
    """Map a named unique/foreign-key constraint to the DomainError it means."""
    _constraint_errors[constraint_name] = factory


def _driver_error(error: DBAPIError) -> BaseException | None:
    orig = error.orig
    if orig is None:
        return None
    return orig.__cause__ or orig


def to_domain_error(error: DBAPIError) -> DomainError | None:
    """Translate a database error into the DomainError it represents, if it is a known one."""
    driver_error = _driver_error(error)
    sqlstate = getattr(driver_error, "sqlstate", None)
    if sqlstate in (LOCK_NOT_AVAILABLE, DEADLOCK_DETECTED):
        return LockConflict()
    if sqlstate not in (UNIQUE_VIOLATION, FOREIGN_KEY_VIOLATION):
        return None
    constraint = getattr(driver_error, "constraint_name", None)
    if not isinstance(constraint, str):
        return None
    if constraint in _constraint_errors:
        return _constraint_errors[constraint]()
    if sqlstate != UNIQUE_VIOLATION:
        return None
    aggregate_class = _primary_keys.get(constraint)
    match = _KEY_ID.search(str(getattr(driver_error, "detail", "") or ""))
    if aggregate_class is None or match is None:
        return None
    return AggregateAlreadyExists(
        namespace=aggregate_class.error_namespace(),
        aggregate_type=aggregate_class.aggregate_type(),
        aggregate_id=UUID(match.group(1)),
    )
