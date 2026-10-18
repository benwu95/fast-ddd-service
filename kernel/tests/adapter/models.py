"""Test-only aggregate used by the kernel's own tests (not shipped to services)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

import pendulum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload
from sqlalchemy.orm.interfaces import ORMOption

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.context import current_user
from fast_ddd.errors import DomainError, ErrorKind
from fast_ddd.events import DomainEvent
from fast_ddd_adapter.orm import Base
from fast_ddd_adapter.repository import (
    AggregateModel,
    ArchiveModel,
    RepositoryBase,
    TenantScope,
)


class Status(StrEnum):
    ACTIVE = "active"
    VOIDED = "voided"


@dataclass(frozen=True, slots=True)
class Line:
    line_id: UUID
    qty: int


@dataclass(frozen=True, kw_only=True)
class OrderCreated(DomainEvent):
    code: str


@dataclass(frozen=True, kw_only=True)
class OrderVoided(DomainEvent):
    reason: str


@dataclass
class OrderAlreadyVoided(DomainError):
    code: ClassVar[str] = "kernel_test.order.already_voided"
    kind: ClassVar[ErrorKind] = ErrorKind.CONFLICT
    message: ClassVar[str] = "Order {orderId} is already voided"

    order_id: UUID


class Order(AggregateRoot):
    bounded_context: ClassVar[str] = "kernel_test"

    def __init__(
        self,
        *,
        id: UUID,
        organization_id: UUID | None,
        code: str,
        lines: list[Line],
        status: Status = Status.ACTIVE,
        version: int = 0,
        created_at: pendulum.DateTime | None = None,
        updated_at: pendulum.DateTime | None = None,
    ) -> None:
        super().__init__(
            id=id,
            organization_id=organization_id,
            version=version,
            created_at=created_at,
            updated_at=updated_at,
        )
        self.code = code
        self.lines = lines
        self.status = status

    @classmethod
    def create(cls, *, id: UUID, organization_id: UUID | None, code: str) -> "Order":
        order = cls(id=id, organization_id=organization_id, code=code, lines=[])
        order.add_event(OrderCreated(doer=current_user(), code=code))
        return order

    def void(self, reason: str) -> None:
        if self.status is Status.VOIDED:
            raise OrderAlreadyVoided(order_id=self.id)
        self.status = Status.VOIDED
        self.add_event(OrderVoided(doer=current_user(), reason=reason))

    def change_line(self, line_id: UUID, qty: int) -> None:
        self.lines = [
            Line(line.line_id, qty) if line.line_id == line_id else line for line in self.lines
        ]


class OrderModel(AggregateModel):
    __tablename__ = "kernel_test_order"

    code: Mapped[str] = mapped_column(String(50), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    lines: Mapped[list["OrderLineModel"]] = relationship(
        lazy="raise", cascade="all, delete-orphan", passive_deletes=True
    )


class OrderLineModel(Base):
    __tablename__ = "kernel_test_order_line"

    line_id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("kernel_test_order.id", ondelete="CASCADE"))
    qty: Mapped[int]


class OrderArchiveModel(ArchiveModel):
    __tablename__ = "kernel_test_order_archive"

    organization_id: Mapped[UUID | None]
    version: Mapped[int]
    code: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20))


class OrderRepository(RepositoryBase[UUID, Order, OrderModel]):
    aggregate_class = Order
    model_class = OrderModel
    tenant_scope: ClassVar[TenantScope] = "organization"
    search_key_fields: ClassVar = {
        "code": OrderModel.code,
        "id": OrderModel.id,
    }
    sort_by_fields: ClassVar = {"code": OrderModel.code, "created_at": OrderModel.created_at}

    def load_options(self) -> list[ORMOption]:
        return [selectinload(OrderModel.lines)]

    def child_models(self, model: OrderModel) -> list[Base]:
        return list(model.lines)

    def model_to_entity(self, model: OrderModel) -> Order:
        return Order(
            id=model.id,
            organization_id=model.organization_id,
            code=model.code,
            lines=[Line(line.line_id, line.qty) for line in model.lines],
            status=Status(model.status),
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def entity_to_model(self, entity: Order, model: OrderModel | None) -> OrderModel:
        if model is None:
            model = OrderModel(id=entity.id, lines=[])
        model.organization_id = entity.organization_id
        model.version = entity.version
        model.created_at = entity.created_at
        model.updated_at = entity.updated_at
        model.code = entity.code
        model.status = entity.status.value
        existing = {line.line_id: line for line in model.lines}
        wanted = {line.line_id for line in entity.lines}
        for line in entity.lines:
            if line.line_id in existing:
                existing[line.line_id].qty = line.qty
            else:
                model.lines.append(OrderLineModel(line_id=line.line_id, qty=line.qty))
        model.lines = [line for line in model.lines if line.line_id in wanted]
        return model


class ArchivedOrderRepository(OrderRepository):
    tenant_scope: ClassVar[TenantScope] = "organization"
    archive_model_class = OrderArchiveModel
