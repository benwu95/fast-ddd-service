from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import ClassVar
from uuid import UUID, uuid4

import pendulum
import pytest

from fast_ddd.aggregate import AggregateRoot, new_id
from fast_ddd.batch import BatchItem, apply_batch, create_batch
from fast_ddd.context import (
    ContextNotSetError,
    User,
    current_organization_id,
    current_parent_event_id,
    current_user,
    is_tenant_exempt,
    tenant_exemption,
    unit_of_work_context,
)
from fast_ddd.errors import (
    AggregateNotFound,
    DomainError,
    ErrorKind,
    VersionMismatch,
    validate_error_code,
)
from fast_ddd.event_bus import EventBus
from fast_ddd.events import DomainEvent
from fast_ddd.serialization import format_datetime, to_json

DOER = User(id="user-1", name="Tester")
ORG = uuid4()


class Status(Enum):
    ACTIVE = "active"
    VOIDED = "voided"


@dataclass(frozen=True, kw_only=True)
class InvoiceVoided(DomainEvent):
    reason: str


@dataclass
class InvoiceAlreadyVoided(DomainError):
    code: ClassVar[str] = "billing.invoice.already_voided"
    kind: ClassVar[ErrorKind] = ErrorKind.CONFLICT
    message: ClassVar[str] = "Invoice {invoiceId} was voided at {voidedAt}"

    invoice_id: UUID
    voided_at: pendulum.DateTime


class Invoice(AggregateRoot):
    bounded_context: ClassVar[str] = "billing"

    def __init__(self, *, id: UUID, organization_id: UUID | None, version: int = 0) -> None:
        super().__init__(id=id, organization_id=organization_id, version=version)
        self.status = Status.ACTIVE
        self.voided_at: pendulum.DateTime | None = None

    def void(self, reason: str) -> None:
        if self.voided_at is not None:
            raise InvoiceAlreadyVoided(invoice_id=self.id, voided_at=self.voided_at)
        self.status = Status.VOIDED
        self.voided_at = pendulum.now("UTC")
        self.add_event(InvoiceVoided(doer=current_user(), reason=reason))


class FakeRepository:
    def __init__(self, *aggregates: Invoice) -> None:
        self.rows = {a.id: a for a in aggregates}
        self.saved: list[Invoice] = []
        self.loaded_with_lock: bool | None = None

    async def load_many(self, ids: Sequence[UUID], *, lock: bool) -> dict[UUID, Invoice]:
        self.loaded_with_lock = lock
        return {i: self.rows[i] for i in ids if i in self.rows}

    async def save_many(self, aggregates: Sequence[Invoice]) -> None:
        self.saved.extend(aggregates)


def test_context_requires_unit_of_work() -> None:
    with pytest.raises(ContextNotSetError):
        current_user()
    with pytest.raises(ContextNotSetError):
        current_organization_id()


def test_context_is_restored_after_scope() -> None:
    with unit_of_work_context(user=DOER, organization_id=ORG):
        assert current_user() == DOER
        assert current_organization_id() == ORG
        with tenant_exemption():
            assert is_tenant_exempt()
        assert not is_tenant_exempt()
    with pytest.raises(ContextNotSetError):
        current_user()


def test_add_event_copies_source_aggregate_and_tracing() -> None:
    with unit_of_work_context(user=DOER, organization_id=ORG, trace_id="t-1"):
        invoice = Invoice(id=new_id(), organization_id=ORG)
        invoice.void("typo")

    (event,) = invoice.domain_events
    assert isinstance(event, InvoiceVoided)
    assert event.organization_id == ORG
    assert event.aggregate_type == "invoice"
    assert event.aggregate_id == invoice.id
    assert event.trace_id == "t-1"
    assert event.doer == DOER
    assert invoice.pull_events() == [event]
    assert invoice.domain_events == ()


async def test_event_bus_sets_parent_event_and_event_organization() -> None:
    bus = EventBus()
    seen: list[tuple[UUID | None, UUID | None, bool]] = []

    async def handler(_event: InvoiceVoided) -> None:
        seen.append((current_parent_event_id(), current_organization_id(), is_tenant_exempt()))

    bus.subscribe(InvoiceVoided, handler)
    other_org = uuid4()
    with unit_of_work_context(user=DOER, organization_id=None):
        event = InvoiceVoided(doer=DOER, reason="x", organization_id=other_org)
        with tenant_exemption():
            await bus.dispatch([event])
        assert current_parent_event_id() is None

    assert seen == [(event.event_id, other_org, False)]


def test_domain_error_params_detail_and_registry() -> None:
    voided_at = pendulum.datetime(2026, 10, 17, 2, 0, 0, tz="UTC")
    invoice_id = uuid4()
    error = InvoiceAlreadyVoided(invoice_id=invoice_id, voided_at=voided_at)

    assert error.params() == {
        "invoiceId": str(invoice_id),
        "voidedAt": "2026-10-17T02:00:00.000Z",
    }
    assert error.detail() == f"Invoice {invoice_id} was voided at 2026-10-17T02:00:00.000Z"
    assert DomainError.registry["billing.invoice.already_voided"] is InvoiceAlreadyVoided


def test_error_code_validation_and_duplicates() -> None:
    assert validate_error_code("auth.token_expired") == "auth.token_expired"
    for bad in ("Auth.token", "single", "a.b.c.d.e", "a." + "b" * 70):
        with pytest.raises(ValueError, match="invalid error code"):
            validate_error_code(bad)

    def define_duplicate() -> type[DomainError]:
        @dataclass
        class DuplicateCode(DomainError):
            code: ClassVar[str] = "billing.invoice.already_voided"
            kind: ClassVar[ErrorKind] = ErrorKind.CONFLICT
            message: ClassVar[str] = "dup"

        return DuplicateCode

    with pytest.raises(ValueError, match="duplicate error code"):
        define_duplicate()


def test_not_found_code_comes_from_aggregate_namespace() -> None:
    error = AggregateNotFound(
        namespace=Invoice.error_namespace(), aggregate_type="invoice", aggregate_id=uuid4()
    )
    assert error.error_code == "billing.invoice.not_found"
    assert error.kind is ErrorKind.NOT_FOUND


def test_to_json_handles_domain_types() -> None:
    @dataclass
    class Line:
        line_id: UUID
        amount: Decimal
        status: Status
        at: pendulum.DateTime

    line_id = uuid4()
    line = Line(line_id, Decimal("10.50"), Status.VOIDED, pendulum.datetime(2026, 1, 1, tz="UTC"))

    assert to_json(line, camel_case=True) == {
        "lineId": str(line_id),
        "amount": "10.50",
        "status": "voided",
        "at": "2026-01-01T00:00:00.000Z",
    }
    assert to_json({"lines": (Status.ACTIVE,)}) == {"lines": ["active"]}
    with pytest.raises(ValueError, match="naive"):
        format_datetime(pendulum.naive(2026, 1, 1))
    with pytest.raises(TypeError):
        to_json(object())


async def test_apply_batch_collects_failures_and_saves_successes() -> None:
    with unit_of_work_context(user=DOER, organization_id=ORG):
        ok = Invoice(id=new_id(), organization_id=ORG, version=1)
        stale = Invoice(id=new_id(), organization_id=ORG, version=2)
        voided = Invoice(id=new_id(), organization_id=ORG, version=1)
        voided.void("earlier")
        missing = new_id()
        repo = FakeRepository(ok, stale, voided)

        result = await apply_batch(
            repo,
            Invoice,
            [
                BatchItem(ok.id, "r", expected_version=1),
                BatchItem(stale.id, "r", expected_version=1),
                BatchItem(voided.id, "r"),
                BatchItem(missing, "r"),
            ],
            lambda invoice, reason: invoice.void(reason),
        )

    assert repo.loaded_with_lock is True
    assert list(result.succeeded) == [ok.id]
    assert repo.saved == [ok]
    assert isinstance(result.failed[stale.id], VersionMismatch)
    assert isinstance(result.failed[voided.id], InvoiceAlreadyVoided)
    assert isinstance(result.failed[missing], AggregateNotFound)


async def test_create_batch_saves_created_aggregates() -> None:
    repo = FakeRepository()
    ids = [new_id(), new_id()]

    result = await create_batch(
        repo,
        [BatchItem(i, None) for i in ids],
        lambda i, _: Invoice(id=i, organization_id=ORG),
    )

    assert [a.id for a in repo.saved] == ids
    assert all(a.is_new for a in result.succeeded.values())


def test_restore_events_prepends_original_events_without_changing_metadata() -> None:
    with unit_of_work_context(user=DOER, organization_id=ORG):
        invoice = Invoice(id=new_id(), organization_id=ORG)
        invoice.void("first")
        original = invoice.pull_events()
        invoice.add_event(InvoiceVoided(doer=DOER, reason="later"))
        later = invoice.domain_events[0]
        invoice.restore_events(original)
    assert invoice.domain_events == (*original, later)
    assert invoice.domain_events[0] is original[0]
    assert invoice.domain_events[-1] is later
