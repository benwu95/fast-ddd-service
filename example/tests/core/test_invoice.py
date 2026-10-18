from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

import pytest
from fast_ddd.context import User

from app.core.billing.domain.errors import InvoiceAlreadyVoided, InvoiceHasNoLines
from app.core.billing.domain.events import (
    InvoiceDeleted,
    InvoiceIssued,
    InvoiceUpdated,
    InvoiceVoided,
)
from app.core.billing.domain.invoice import (
    Invoice,
    InvoiceId,
    InvoiceLine,
    InvoiceStatus,
)
from tests.support import content

DOER = User(id="user-1", name="Ann")


def issued(**kwargs: object) -> Invoice:
    invoice = Invoice.issue(
        id=InvoiceId(uuid4()), organization_id=uuid4(), content=content(), doer=DOER, **kwargs
    )
    invoice.pull_events()
    return invoice


def test_issue_records_the_invoice_and_its_event() -> None:
    organization_id = uuid4()
    lines = (InvoiceLine("A", 2, Decimal("10.25")), InvoiceLine("B", 1, Decimal("0.50")))
    invoice = Invoice.issue(
        id=InvoiceId(uuid4()),
        organization_id=organization_id,
        content=content(lines=lines),
        doer=DOER,
    )

    assert invoice.total == Decimal("21.00")
    assert invoice.status is InvoiceStatus.ACTIVE
    (event,) = invoice.pull_events()
    assert isinstance(event, InvoiceIssued)
    assert (event.number, event.total, event.doer) == ("INV-001", Decimal("21.00"), DOER)
    assert (event.organization_id, event.aggregate_id) == (organization_id, invoice.id)


def test_an_invoice_needs_lines() -> None:
    with pytest.raises(InvoiceHasNoLines):
        Invoice.issue(
            id=InvoiceId(uuid4()), organization_id=uuid4(), content=content(lines=()), doer=DOER
        )
    invoice = issued()
    with pytest.raises(InvoiceHasNoLines):
        invoice.update(content(lines=()), DOER)


def test_update_replaces_content_and_skips_no_op_updates() -> None:
    invoice = issued()

    invoice.update(invoice.content, DOER)
    assert invoice.pull_events() == []

    invoice.update(content("INV-002", note="late"), DOER)
    assert invoice.content.number == "INV-002"
    (event,) = invoice.pull_events()
    assert isinstance(event, InvoiceUpdated)


def test_void_moves_active_to_voided_once() -> None:
    invoice = issued()

    invoice.void("duplicate", DOER)

    assert invoice.status is InvoiceStatus.VOIDED
    assert invoice.void_reason == "duplicate"
    assert invoice.voided_at is not None
    (event,) = invoice.pull_events()
    assert isinstance(event, InvoiceVoided)
    with pytest.raises(InvoiceAlreadyVoided) as error:
        invoice.void("again", DOER)
    assert invoice.voided_at is not None
    assert error.value.params() == {
        "invoiceId": str(invoice.id),
        "voidedAt": invoice.voided_at.format("YYYY-MM-DDTHH:mm:ss.SSS") + "Z",
    }


def update(invoice: Invoice) -> None:
    invoice.update(content("INV-009"), DOER)


def delete(invoice: Invoice) -> None:
    invoice.delete(DOER)


@pytest.mark.parametrize("command", [update, delete])
def test_voided_invoices_are_frozen(command: Callable[[Invoice], None]) -> None:
    invoice = issued()
    invoice.void("duplicate", DOER)

    with pytest.raises(InvoiceAlreadyVoided):
        command(invoice)


def test_delete_marks_the_aggregate_and_records_the_number() -> None:
    invoice = issued()

    invoice.delete(DOER)

    assert invoice.is_delete
    (event,) = invoice.pull_events()
    assert isinstance(event, InvoiceDeleted)
    assert event.number == "INV-001"
