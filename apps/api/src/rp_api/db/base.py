from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {datetime: DateTime(timezone=True), uuid.UUID: PG_UUID(as_uuid=True)}

    # Scope marker consumed by the migration RLS helper (see db/rls.py)
    __scope__ = "tenant"

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        table = cls.__dict__.get("__table__")
        if table is not None:
            table.info["scope"] = getattr(cls, "__scope__", "tenant")


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, server_default=func.now())


class TenantMixin(IdMixin, TimestampMixin):
    """Tenant-owned row: UUID PK, tenant_id (RLS), timestamps and optimistic version."""

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)

    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)


class GlobalMixin(IdMixin, TimestampMixin):
    """Global reference row: no tenant ID; writable only by the ingestion/admin role."""
