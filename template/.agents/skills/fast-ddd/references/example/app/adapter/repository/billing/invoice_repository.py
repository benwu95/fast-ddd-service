from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

import pendulum
from fast_ddd.repository import SearchPage
from fast_ddd_adapter.db_errors import register_constraint_error
from fast_ddd_adapter.orm import Base
from fast_ddd_adapter.repository import RepositoryBase, TenantScope
from sqlalchemy import ColumnElement, distinct, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.interfaces import ORMOption

from app.adapter.repository.billing.invoice_model import InvoiceLineModel, InvoiceModel
from app.core.billing.domain.errors import InvoiceNumberTaken
from app.core.billing.domain.invoice import (
    Customer,
    CustomerId,
    Invoice,
    InvoiceContent,
    InvoiceId,
    InvoiceLine,
    InvoiceStatus,
)

register_constraint_error("uq_billing_invoice_organization_id_number", InvoiceNumberTaken)


@dataclass(frozen=True, slots=True)
class InvoiceTotals:
    count: int
    amount: Decimal


class InvoiceRepository(RepositoryBase[InvoiceId, Invoice, InvoiceModel]):
    aggregate_class = Invoice
    model_class = InvoiceModel
    tenant_scope: ClassVar[TenantScope] = "organization"
    search_key_fields: ClassVar = {
        "number": InvoiceModel.number,
        "customer_name": InvoiceModel.customer_name,
    }
    sort_by_fields: ClassVar = {
        "created_at": InvoiceModel.created_at,
        "number": InvoiceModel.number,
    }

    def load_options(self) -> list[ORMOption]:
        return [selectinload(InvoiceModel.lines)]

    def child_models(self, model: InvoiceModel) -> list[Base]:
        return list(model.lines)

    def model_to_entity(self, model: InvoiceModel) -> Invoice:
        return Invoice(
            id=InvoiceId(model.id),
            organization_id=model.organization_id,
            content=InvoiceContent(
                number=model.number,
                customer=Customer(
                    id=CustomerId(model.customer_id),
                    name=model.customer_name,
                    tax_id=model.customer_tax_id,
                ),
                lines=tuple(
                    InvoiceLine(line.description, line.quantity, line.unit_price)
                    for line in model.lines
                ),
                note=model.note,
            ),
            status=InvoiceStatus(model.status),
            void_reason=model.void_reason,
            voided_at=model.voided_at,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def entity_to_model(self, entity: Invoice, model: InvoiceModel | None) -> InvoiceModel:
        if model is None:
            model = InvoiceModel(id=entity.id, lines=[])
        content = entity.content
        model.organization_id = entity.organization_id
        model.version = entity.version
        model.created_at = entity.created_at
        model.updated_at = entity.updated_at
        model.number = content.number
        model.customer_id = content.customer.id
        model.customer_name = content.customer.name
        model.customer_tax_id = content.customer.tax_id
        model.note = content.note
        model.status = entity.status.value
        model.void_reason = entity.void_reason
        model.voided_at = entity.voided_at
        # Lines are value objects: replace them all, but only when they changed, so an
        # unchanged invoice keeps its version.
        current = [(line.description, line.quantity, line.unit_price) for line in model.lines]
        wanted = [(line.description, line.quantity, line.unit_price) for line in content.lines]
        if current != wanted:
            model.lines = [
                InvoiceLineModel(
                    position=position, description=description, quantity=quantity, unit_price=price
                )
                for position, (description, quantity, price) in enumerate(wanted)
            ]
        return model

    async def search_invoices(
        self,
        *,
        statuses: Sequence[InvoiceStatus] = (),
        customer_ids: Sequence[CustomerId] = (),
        search_key_fields: Sequence[str] = (),
        search_keys: Sequence[str] = (),
        sort_by: Sequence[str] = (),
        offset: int = 0,
        limit: int,
    ) -> SearchPage[Invoice]:
        filters: list[ColumnElement[bool]] = []
        if statuses:
            filters.append(InvoiceModel.status.in_([status.value for status in statuses]))
        if customer_ids:
            filters.append(InvoiceModel.customer_id.in_(customer_ids))
        return await self.search(
            filters,
            search_key_fields=search_key_fields,
            search_keys=search_keys,
            sort_by=sort_by,
            offset=offset,
            limit=limit,
        )

    async def active_ids_of_customer(
        self,
        customer_id: CustomerId,
        *,
        among: Sequence[InvoiceId] | None = None,
        lock: bool = False,
    ) -> list[InvoiceId]:
        stmt = select(InvoiceModel.id).where(
            InvoiceModel.customer_id == customer_id,
            InvoiceModel.status == InvoiceStatus.ACTIVE.value,
            *self.tenant_conditions(),
        )
        if among is not None:
            stmt = stmt.where(InvoiceModel.id.in_(among))
        if lock:
            # Id order, as load_many locks, so concurrent chunks cannot deadlock.
            stmt = stmt.order_by(InvoiceModel.id).with_for_update()
        return [InvoiceId(id) for id in (await self.session.scalars(stmt)).all()]

    async def organizations_issuing_since(self, since: pendulum.DateTime) -> list[UUID]:
        """Every organization with new invoices; call it inside ``system_context()``."""
        stmt = (
            select(InvoiceModel.organization_id)
            .distinct()
            .where(InvoiceModel.created_at >= since, *self.tenant_conditions())
            .order_by(InvoiceModel.organization_id)
        )
        return [org for org in (await self.session.scalars(stmt)).all() if org is not None]

    async def totals_since(self, since: pendulum.DateTime) -> InvoiceTotals:
        amount = func.coalesce(
            func.sum(InvoiceLineModel.quantity * InvoiceLineModel.unit_price), Decimal(0)
        )
        stmt = (
            select(func.count(distinct(InvoiceModel.id)), amount)
            .select_from(InvoiceModel)
            .outerjoin(InvoiceLineModel)
            .where(
                InvoiceModel.created_at >= since,
                InvoiceModel.status == InvoiceStatus.ACTIVE.value,
                *self.tenant_conditions(),
            )
        )
        count, total = (await self.session.execute(stmt)).one()
        return InvoiceTotals(count=count, amount=Decimal(total))
