from datetime import datetime
from typing import Any, ClassVar, override
from uuid import UUID

import pendulum
from sqlalchemy import JSON, DateTime, Dialect, Index, Integer, MetaData, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator[pendulum.DateTime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    @override
    def process_bind_param(
        self, value: pendulum.DateTime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed")
        return value

    @override
    def process_result_value(self, value: Any | None, dialect: Dialect) -> pendulum.DateTime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected datetime, got {type(value).__name__}")
        return pendulum.instance(value).in_timezone("UTC")


class Base(DeclarativeBase):
    """Declarative base shared by kernel and service models (one MetaData)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        pendulum.DateTime: UtcDateTime,
        UUID: Uuid(as_uuid=True),
        dict[str, Any]: JSON().with_variant(JSONB(), "postgresql"),
    }


class ProcessedMessage(Base):
    """Inbox: a subscriber processed this event (RabbitMQ delivers at least once)."""

    __tablename__ = "processed_message"

    subscriber: Mapped[str] = mapped_column(String(200), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    processed_at: Mapped[pendulum.DateTime]


class DomainEventModel(Base):
    __tablename__ = "domain_event"
    __table_args__ = (
        Index(
            "ix_domain_event_aggregate",
            "organization_id",
            "aggregate_type",
            "aggregate_id",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer)
    organization_id: Mapped[UUID | None]
    aggregate_type: Mapped[str] = mapped_column(String(200))
    aggregate_id: Mapped[UUID | None]
    doer: Mapped[dict[str, Any]]
    body: Mapped[dict[str, Any]]
    occurred_at: Mapped[pendulum.DateTime]
    trace_id: Mapped[str | None] = mapped_column(String(64))
    parent_event_id: Mapped[UUID | None]
