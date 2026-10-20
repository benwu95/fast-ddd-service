from typing import Protocol

from fast_ddd.repository import Repository

from app.core.billing.domain.invoice import Invoice, InvoiceId


class InvoiceRepositoryInterface(Repository[InvoiceId, Invoice], Protocol):
    async def load(self, id: InvoiceId, *, lock: bool) -> Invoice: ...

    async def save(self, aggregate: Invoice) -> None: ...
