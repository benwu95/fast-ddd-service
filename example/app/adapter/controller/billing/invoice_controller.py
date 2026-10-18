import logging
from collections.abc import Sequence
from itertools import batched
from uuid import UUID

import pendulum
from fast_ddd.aggregate import new_id
from fast_ddd.batch import BatchItem
from fast_ddd.context import current_organization_id, current_user
from fast_ddd.repository import SearchPage
from fast_ddd.serialization import format_datetime
from fast_ddd_adapter.commands import merge
from fast_ddd_adapter.controller import BatchOutcome, execute, run_batch
from fast_ddd_adapter.infrastructure import system_context, task_queue
from fast_ddd_adapter.repository import TenantContextMissingError

from app.adapter.controller.billing.invoice_commands import (
    CreateInvoiceCommand,
    SearchInvoicesQuery,
    UpdateInvoiceCommand,
)
from app.adapter.controller.billing.task_names import SEND_DAILY_SUMMARY
from app.adapter.repository.billing.invoice_repository import InvoiceRepository
from app.adapter.resources import resources
from app.core.billing.domain.invoice import CustomerId, Invoice, InvoiceContent, InvoiceId
from app.core.billing.use_case.invoice_use_case import InvoiceUseCase

logger = logging.getLogger(__name__)

# Bulk work from messages runs in chunks of the HTTP batch limit, to bound how many rows
# one statement locks.
BULK_CHUNK_SIZE = 100


def _organization_id() -> UUID:
    organization_id = current_organization_id()
    if organization_id is None:
        raise TenantContextMissingError("invoices belong to an organization")
    return organization_id


class InvoiceController:
    """Every entry point (HTTP, MQ, tasks) reaches the use case through these methods."""

    def __init__(self) -> None:
        self._repository = InvoiceRepository()
        self._use_case = InvoiceUseCase(self._repository)

    async def get(self, invoice_id: InvoiceId) -> Invoice:
        return await execute(lambda: self._repository.load(invoice_id, lock=False))

    async def search(self, query: SearchInvoicesQuery) -> SearchPage[Invoice]:
        return await execute(
            lambda: self._repository.search_invoices(
                statuses=query.statuses,
                customer_ids=query.customer_ids,
                search_key_fields=query.search_key_fields,
                search_keys=query.search_keys,
                sort_by=query.sort_by,
                offset=query.offset,
                limit=query.limit,
            )
        )

    async def create(self, command: CreateInvoiceCommand) -> Invoice:
        organization_id = _organization_id()
        invoice_id = command.invoice_id or InvoiceId(new_id())
        return await execute(
            lambda: self._use_case.issue(
                invoice_id, organization_id, command.content, current_user()
            )
        )

    async def update(self, command: UpdateInvoiceCommand) -> Invoice:
        async def update() -> Invoice:
            # An unlocked read to fill in what the client did not send; the use case reloads
            # with a lock and checks the version, so a stale read here ends in 412.
            current = (await self._repository.load(command.invoice_id, lock=False)).content
            content = InvoiceContent(
                number=merge(command.number, current.number),
                customer=merge(command.customer, current.customer),
                lines=merge(command.lines, current.lines),
                note=merge(command.note, current.note),
            )
            return await self._use_case.update(
                command.invoice_id, content, command.expected_version, current_user()
            )

        return await execute(update)

    async def delete(self, invoice_id: InvoiceId, expected_version: int) -> None:
        await execute(lambda: self._use_case.delete(invoice_id, expected_version, current_user()))

    async def void(self, invoice_id: InvoiceId, reason: str, expected_version: int) -> Invoice:
        return await execute(
            lambda: self._use_case.void(invoice_id, reason, expected_version, current_user())
        )

    async def void_many(
        self, items: Sequence[BatchItem[InvoiceId, str]]
    ) -> BatchOutcome[InvoiceId, Invoice]:
        doer = current_user()
        return await run_batch(
            items,
            batch=lambda batch: self._use_case.void_many(batch, doer),
            single=lambda item: self._use_case.void(
                item.id, item.payload, item.expected_version, doer
            ),
        )

    async def void_customer_invoices(self, customer_id: CustomerId, reason: str) -> None:
        """Void every active invoice of a customer; transient failures raise for a retry."""
        doer = current_user()
        invoice_ids = await execute(lambda: self._repository.active_ids_of_customer(customer_id))
        for chunk in batched(invoice_ids, BULK_CHUNK_SIZE, strict=False):
            outcome = await run_batch(
                [BatchItem(invoice_id, reason) for invoice_id in chunk],
                batch=lambda batch: self._use_case.void_many(batch, doer),
                single=lambda item: self._use_case.void(item.id, item.payload, None, doer),
                raise_on_transient=True,
            )
            for invoice_id, result in outcome.results.items():
                if not isinstance(result, Invoice):
                    logger.warning("invoice %s was not voided: %s", invoice_id, result)

    async def send_void_notice(self, invoice_id: InvoiceId) -> None:
        invoice = await self.get(invoice_id)
        await resources().notification.send(
            f"invoice-voided-{invoice.id}",
            organization_id=_organization_id(),
            kind="invoice_voided",
            data={
                "invoiceId": str(invoice.id),
                "number": invoice.content.number,
                "reason": invoice.void_reason or "",
            },
        )

    async def enqueue_daily_summaries(self) -> None:
        """Fan out one summary task per organization that issued invoices in the last day."""
        since = pendulum.now("UTC").subtract(days=1)

        async def enqueue() -> None:
            with system_context("daily invoice summary fan-out"):
                organizations = await self._repository.organizations_issuing_since(since)
            for organization_id in organizations:
                await task_queue().enqueue(
                    SEND_DAILY_SUMMARY,
                    {"since": format_datetime(since)},
                    organization_id=organization_id,
                    dedupe_key=f"{SEND_DAILY_SUMMARY}:{organization_id}:{since.date()}",
                )

        await execute(enqueue)

    async def send_daily_summary(self, since: pendulum.DateTime) -> None:
        organization_id = _organization_id()
        totals = await execute(lambda: self._repository.totals_since(since))
        await resources().notification.send(
            f"daily-summary-{organization_id}-{since.date().isoformat()}",
            organization_id=organization_id,
            kind="daily_invoice_summary",
            data={
                "since": format_datetime(since),
                "count": totals.count,
                "amount": str(totals.amount),
            },
        )
