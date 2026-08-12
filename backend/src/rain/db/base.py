"""Async engine/session management and the schema-per-tenant plumbing.

Two flavors of session:
  * control_session()  -- queries rain.db.control_models tables (schema="control").
  * tenant_session(schema_name) -- queries rain.db.tenant_models tables, transparently
    redirected to `schema_name` via SQLAlchemy's schema_translate_map. Control-schema
    tables are unaffected (they already carry an explicit schema), so both flavors of
    model can be used from either session if ever needed.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from rain.settings import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@asynccontextmanager
async def control_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


@asynccontextmanager
async def tenant_session(schema_name: str) -> AsyncIterator[AsyncSession]:
    # schema_translate_map is applied at the *engine* level (a lightweight
    # OptionEngine proxy over the same pool, not a new pool) rather than to
    # one Connection checkout: a session that commits mid-request releases
    # its connection back to the pool, and the next statement checks out a
    # fresh one -- if the translate map were only set on the original
    # checkout (session.connection(execution_options=...), the previous,
    # seemingly-more-obvious approach here), that fresh connection has no
    # translate map at all, and an unqualified "FROM tickets" or "FROM
    # notification_channels" query silently lands in the wrong schema
    # (asyncpg.exceptions.UndefinedTableError). Confirmed via real
    # requests with DEBUG=true: this broke any tenant-scoped code that
    # queries again after an earlier commit in the same session, which
    # turned out to be common (ticket/document creation followed by a
    # notification lookup, refresh() after commit, ...). Binding the
    # translate map to the engine instead means every connection this
    # session ever checks out, no matter how many commits happen first,
    # carries it.
    tenant_engine = get_engine().execution_options(schema_translate_map={None: schema_name})
    async with AsyncSession(tenant_engine, expire_on_commit=False) as session:
        yield session
