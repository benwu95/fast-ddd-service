from collections.abc import Sequence
from uuid import UUID

from fast_ddd.batch import BatchItem, BatchResult, apply_batch, check_version
from fast_ddd.context import User

from app.core.billing.domain.invoice import Invoice, InvoiceContent, InvoiceId
from app.core.billing.domain.repository import InvoiceRepositoryInterface


class InvoiceUseCase:
    def __init__(self, repository: InvoiceRepositoryInterface) -> None:
        self._repository = repository

    async def issue(
        self, invoice_id: InvoiceId, organization_id: UUID, content: InvoiceContent, doer: User
    ) -> Invoice:
        invoice = Invoice.issue(
            id=invoice_id, organization_id=organization_id, content=content, doer=doer
        )
        await self._repository.save(invoice)
        return invoice

    async def update(
        self,
        invoice_id: InvoiceId,
        content: InvoiceContent,
        expected_version: int | None,
        doer: User,
    ) -> Invoice:
        invoice = await self._load_checked(invoice_id, expected_version)
        invoice.update(content, doer)
        await self._repository.save(invoice)
        return invoice

    async def delete(self, invoice_id: InvoiceId, expected_version: int | None, doer: User) -> None:
        invoice = await self._load_checked(invoice_id, expected_version)
        invoice.delete(doer)
        await self._repository.save(invoice)

    async def void(
        self, invoice_id: InvoiceId, reason: str, expected_version: int | None, doer: User
    ) -> Invoice:
        invoice = await self._load_checked(invoice_id, expected_version)
        invoice.void(reason, doer)
        await self._repository.save(invoice)
        return invoice

    async def void_many(
        self, items: Sequence[BatchItem[InvoiceId, str]], doer: User
    ) -> BatchResult[InvoiceId, Invoice]:
        return await apply_batch(
            self._repository, Invoice, items, lambda invoice, reason: invoice.void(reason, doer)
        )

    async def _load_checked(self, invoice_id: InvoiceId, expected_version: int | None) -> Invoice:
        invoice = await self._repository.load(invoice_id, lock=True)
        check_version(invoice, expected_version)
        return invoice
