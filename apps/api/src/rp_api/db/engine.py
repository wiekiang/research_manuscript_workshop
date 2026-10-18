"""Database engines per role and tenant-context sessions.

Every transaction opened by an app-role session runs `set_config('app.tenant_id', ...)` so that
PostgreSQL row-level security policies apply. The context is re-applied after each commit because
`set_config(..., true)` is transaction-local.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings


@dataclass
class DbContext:
    tenant_id: UUID | None = None
    user_id: UUID | None = None


_engines: dict[str, AsyncEngine] = {}


def get_engine(role: str = "app") -> AsyncEngine:
    if role not in _engines:
        s = get_settings()
        url = {
            "app": s.database_url,
            "owner": s.database_url_owner,
            "system": s.database_url_system,
            "ingest": s.database_url_ingest,
        }[role].get_secret_value()
        _engines[role] = create_async_engine(url, pool_size=s.db_pool_size, pool_pre_ping=True, future=True)
    return _engines[role]


async def dispose_engines() -> None:
    for eng in list(_engines.values()):
        await eng.dispose()
    _engines.clear()


def _install_context(session: AsyncSession, ctx: DbContext) -> None:
    def _after_begin(sync_session, transaction, connection):  # noqa: ARG001
        connection.exec_driver_sql(
            "SELECT set_config('app.tenant_id', %(t)s, true), set_config('app.user_id', %(u)s, true)",
            {"t": str(ctx.tenant_id) if ctx.tenant_id else "", "u": str(ctx.user_id) if ctx.user_id else ""},
        )

    event.listen(session.sync_session, "after_begin", _after_begin)


@asynccontextmanager
async def session_scope(
    role: str = "app", tenant_id: UUID | None = None, user_id: UUID | None = None
) -> AsyncIterator[AsyncSession]:
    """Yield a session bound to a DB role and tenant context. Caller commits explicitly."""
    maker = async_sessionmaker(get_engine(role), expire_on_commit=False, class_=AsyncSession)
    session = maker()
    ctx = DbContext(tenant_id=tenant_id, user_id=user_id)
    session.info["ctx"] = ctx
    _install_context(session, ctx)
    try:
        yield session
    finally:
        # Detach first so objects read in this scope stay usable; uncommitted changes are discarded.
        session.expunge_all()
        await session.rollback()
        await session.close()


def set_session_tenant(session: AsyncSession, tenant_id: UUID | None, user_id: UUID | None = None) -> None:
    """Change the tenant context for subsequent transactions in this session (e.g. after login)."""
    ctx: DbContext = session.info["ctx"]
    ctx.tenant_id = tenant_id
    if user_id is not None:
        ctx.user_id = user_id


async def apply_context_now(session: AsyncSession) -> None:
    ctx: DbContext = session.info["ctx"]
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
        {"t": str(ctx.tenant_id) if ctx.tenant_id else "", "u": str(ctx.user_id) if ctx.user_id else ""},
    )
