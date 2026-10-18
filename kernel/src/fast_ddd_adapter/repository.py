import dataclasses
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, ClassVar, Literal
from typing import cast as type_cast
from uuid import UUID, uuid4

import pendulum
from sqlalchemy import TEXT, ColumnElement, String, UnaryExpression, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, Mapped, mapped_column
from sqlalchemy.orm.interfaces import ORMOption

from fast_ddd.aggregate import AggregateRoot
from fast_ddd.context import current_organization_id, is_tenant_exempt
from fast_ddd.errors import AggregateNotFound
from fast_ddd.events import DomainEvent
from fast_ddd.repository import SearchPage
from fast_ddd.serialization import to_json
from fast_ddd_adapter.db_errors import register_primary_key
from fast_ddd_adapter.orm import Base, DomainEventModel
from fast_ddd_adapter.session import SessionProvider, current_session_provider

type TenantScope = Literal["organization", "global"]

_EVENT_BASE_FIELDS = frozenset(f.name for f in dataclasses.fields(DomainEvent))


class TenantContextMissingError(RuntimeError):
    """An organization-scoped repository was used without an organization in context."""


_SEARCH_KEY_FIELD = re.compile(r"^(?:(?P<operator>starts|ends|equals):)?(?P<field>\w+)$")
_SORT_BY = re.compile(r"^(?P<order>[-+]?)(?P<field>\w+)$")


def _search_pattern(operator: str | None, keys: Sequence[str]) -> str:
    alternatives = "|".join(re.escape(key) for key in keys)
    match operator:
        case "starts":
            return f"^({alternatives})"
        case "ends":
            return f"({alternatives})$"
        case "equals":
            return f"^({alternatives})$"
        case _:
            return alternatives


class AggregateModel(Base):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(index=True)
    version: Mapped[int]
    created_at: Mapped[pendulum.DateTime]
    updated_at: Mapped[pendulum.DateTime]


class ArchiveModel(Base):
    __abstract__ = True

    archive_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(index=True)
    archived_at: Mapped[pendulum.DateTime]
    event_id: Mapped[UUID | None]
    event_name: Mapped[str | None] = mapped_column(String(200))


def domain_event_row(event: DomainEvent) -> DomainEventModel:
    body = {
        f.name: to_json(getattr(event, f.name))
        for f in dataclasses.fields(event)
        if f.name not in _EVENT_BASE_FIELDS
    }
    doer = to_json(event.doer)
    return DomainEventModel(
        event_id=event.event_id,
        name=event.name,
        version=event.VERSION,
        organization_id=event.organization_id,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        doer=doer if isinstance(doer, dict) else {},
        body=body,
        occurred_at=event.occurred_at,
        trace_id=event.trace_id,
        parent_event_id=event.parent_event_id,
    )


class RepositoryBase[Id: UUID, A: AggregateRoot, M: AggregateModel](ABC):
    """Collection-oriented repository: one query to load, one flush to save.

    Subclasses must declare ``tenant_scope``; there is no default.
    """

    aggregate_class: ClassVar[type[AggregateRoot]]
    model_class: ClassVar[type[AggregateModel]]
    tenant_scope: ClassVar[TenantScope]
    archive_model_class: ClassVar[type[ArchiveModel] | None] = None
    search_key_fields: ClassVar[Mapping[str, InstrumentedAttribute[Any]]] = {}
    sort_by_fields: ClassVar[Mapping[str, InstrumentedAttribute[Any]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        if "tenant_scope" not in vars(cls):
            raise TypeError(f"{cls.__name__} must declare tenant_scope explicitly")
        register_primary_key(f"pk_{cls.model_class.__tablename__}", cls.aggregate_class)

    @abstractmethod
    def model_to_entity(self, model: M) -> A: ...

    @abstractmethod
    def entity_to_model(self, entity: A, model: M | None) -> M: ...

    def child_models(self, model: M) -> Iterable[Base]:  # noqa: ARG002 - override hook
        return ()

    def load_options(self) -> Sequence[ORMOption]:
        return ()

    @property
    def session(self) -> AsyncSession:
        return current_session_provider().session

    def _model(self) -> type[M]:
        return type_cast(type[M], self.model_class)

    def _organization_scope(self) -> UUID | None:
        if self.tenant_scope == "global" or is_tenant_exempt():
            return None
        organization_id = current_organization_id()
        if organization_id is None:
            raise TenantContextMissingError(
                f"{type(self).__name__} needs an organization; use system_context() for "
                "cross-tenant work"
            )
        return organization_id

    def tenant_conditions(self) -> list[ColumnElement[bool]]:
        """The tenant filter for custom queries: ``select(...).where(..., *conditions)``."""
        organization_id = self._organization_scope()
        return [] if organization_id is None else [self._model().organization_id == organization_id]

    async def load_many(self, ids: Sequence[Id], *, lock: bool) -> dict[Id, A]:
        conditions = self.tenant_conditions()
        if not ids:
            return {}
        model = self._model()
        stmt = select(model).where(model.id.in_(ids), *conditions).order_by(model.id)
        if options := self.load_options():
            stmt = stmt.options(*options)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        provider = current_session_provider()
        rows = (await provider.session.execute(stmt)).scalars().all()
        for row in rows:
            provider.keep_loaded((model, row.id), row)
        return {type_cast(Id, row.id): self.model_to_entity(row) for row in rows}

    async def search(
        self,
        filters: Sequence[ColumnElement[bool]] = (),
        *,
        search_key_fields: Sequence[str] = (),
        search_keys: Sequence[str] = (),
        sort_by: Sequence[str] = (),
        offset: int = 0,
        limit: int,
    ) -> SearchPage[A]:
        """One page plus the total, tenant-filtered; unknown field names are ignored.

        ``search_key_fields`` entries are ``[starts:|ends:|equals:]<field>`` (default: contains)
        and are OR-ed; field and sort names must be listed in ``search_key_fields`` /
        ``sort_by_fields``. The default order is newest first; ``id`` breaks ties.
        """
        model = self._model()
        conditions = [*filters, *self.tenant_conditions()]
        if search_keys:
            key_filter = self._search_key_filter(search_key_fields, search_keys)
            if key_filter is not None:
                conditions.append(key_filter)
        total = await self.session.scalar(
            select(func.count()).select_from(model).where(*conditions)
        )
        stmt = (
            select(model)
            .where(*conditions)
            .order_by(*self._sort_order(sort_by), model.id)
            .offset(offset)
            .limit(limit)
        )
        if options := self.load_options():
            stmt = stmt.options(*options)
        rows = (await self.session.execute(stmt)).scalars().all()
        return SearchPage(total=total or 0, items=[self.model_to_entity(row) for row in rows])

    def _search_key_filter(
        self, fields: Sequence[str], keys: Sequence[str]
    ) -> ColumnElement[bool] | None:
        matches: list[ColumnElement[bool]] = []
        for raw in fields:
            parsed = _SEARCH_KEY_FIELD.match(raw)
            column = self.search_key_fields.get(parsed["field"]) if parsed else None
            if parsed is None or column is None:
                continue
            pattern = _search_pattern(parsed["operator"], keys)
            matches.append(cast(column, TEXT).regexp_match(pattern))
        return or_(*matches) if matches else None

    def _sort_order(self, sort_by: Sequence[str]) -> list[UnaryExpression[Any]]:
        order: list[UnaryExpression[Any]] = []
        used: set[str] = set()
        for raw in sort_by:
            parsed = _SORT_BY.match(raw)
            if parsed is None or parsed["field"] in used:
                continue
            column = self.sort_by_fields.get(parsed["field"])
            if column is not None:
                used.add(parsed["field"])
                order.append(column.desc() if parsed["order"] == "-" else column.asc())
        return order or [self._model().created_at.desc()]

    async def load(self, id: Id, *, lock: bool) -> A:
        found = await self.load_many([id], lock=lock)
        if id not in found:
            raise self._not_found(id)
        return found[id]

    async def save(self, aggregate: A) -> None:
        await self.save_many([aggregate])

    async def save_many(self, aggregates: Sequence[A]) -> None:
        organization_id = self._organization_scope()
        for aggregate in aggregates:
            if self.tenant_scope == "organization" and aggregate.organization_id is None:
                raise TenantContextMissingError(
                    f"{type(aggregate).__name__} {aggregate.id} has no organization_id"
                )
            if organization_id is not None and aggregate.organization_id != organization_id:
                raise self._not_found(aggregate.id)
        provider = current_session_provider()
        session = provider.session
        for aggregate in aggregates:
            events = provider.record_saved(aggregate)
            await self._persist(provider, aggregate, events)
            session.add_all([domain_event_row(event) for event in events])
        await session.flush()

    async def _persist(
        self, provider: SessionProvider, aggregate: A, events: list[DomainEvent]
    ) -> None:
        session = provider.session
        if aggregate.is_new:
            aggregate.version = 1
            aggregate.updated_at = aggregate.created_at
            session.add(self.entity_to_model(aggregate, None))
            return
        model_class = self._model()
        model = type_cast(M | None, provider.loaded((model_class, aggregate.id)))
        if model is None:
            stmt = (
                select(model_class)
                .where(model_class.id == aggregate.id, *self.tenant_conditions())
                .options(*self.load_options())
                .execution_options(populate_existing=True)
            )
            model = (await session.scalars(stmt)).one_or_none()
            if model is not None:
                provider.keep_loaded((model_class, aggregate.id), model)
        if model is None:
            raise self._not_found(aggregate.id)
        organization_id = self._organization_scope()
        if organization_id is not None and model.organization_id != organization_id:
            raise self._not_found(aggregate.id)
        if aggregate.is_delete:
            self._archive(session, model, events)
            await session.delete(model)
            return
        aggregate.version = model.version
        aggregate.updated_at = model.updated_at
        self.entity_to_model(aggregate, model)
        if session.is_modified(model) or any(
            session.is_modified(c) for c in self.child_models(model)
        ):
            now = pendulum.now("UTC")
            model.version = aggregate.version + 1
            model.updated_at = now
            aggregate.version = model.version
            aggregate.updated_at = now
            self._archive(session, model, events)

    def _archive(self, session: AsyncSession, model: M, events: list[DomainEvent]) -> None:
        archive_class = self.archive_model_class
        if archive_class is None:
            return
        snapshot = archive_class()
        for column in model.__table__.columns:
            if hasattr(archive_class, column.key):
                setattr(snapshot, column.key, getattr(model, column.key))
        snapshot.archive_id = uuid4()
        snapshot.archived_at = pendulum.now("UTC")
        last_event = events[-1] if events else None
        snapshot.event_id = last_event.event_id if last_event else None
        snapshot.event_name = last_event.name if last_event else None
        session.add(snapshot)

    def _not_found(self, id: UUID) -> AggregateNotFound:
        return AggregateNotFound(
            namespace=self.aggregate_class.error_namespace(),
            aggregate_type=self.aggregate_class.aggregate_type(),
            aggregate_id=id,
        )
