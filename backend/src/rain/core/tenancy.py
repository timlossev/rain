"""Per-request identity + tenant resolution.

Every authenticated route depends (directly or transitively) on
get_current_user, and every tenant-scoped route additionally depends on
get_tenant_db, which resolves the active tenant and hands back a session
whose queries are transparently redirected to that tenant's schema (see
rain.db.base.tenant_session).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.security import SESSION_COOKIE_NAME, hash_session_token
from rain.db.base import control_session, tenant_session
from rain.db.control_models import Session as SessionRow
from rain.db.control_models import Tenant, User


class AuthRequiredError(Exception):
    """No valid session present. A FastAPI exception handler turns this
    into a redirect to /login?next=<path>."""


class TenantRequiredError(Exception):
    """Route needs an active tenant but none is selected -- an
    internal_admin who hasn't used the tenant switcher yet, or a client
    account with no tenant assigned. Handled as a redirect to a tenant
    picker."""


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    display_name: str
    role_key: str
    home_tenant_id: int | None

    @property
    def is_internal_admin(self) -> bool:
        return self.role_key == "internal_admin"


@dataclass(frozen=True)
class RequestContext:
    user: CurrentUser
    control_db: AsyncSession
    active_tenant: Tenant | None


async def get_control_db() -> AsyncSession:
    async with control_session() as session:
        yield session


async def get_current_user(request: Request, control_db: AsyncSession = Depends(get_control_db)) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise AuthRequiredError()

    token_hash = hash_session_token(token)
    result = await control_db.execute(select(SessionRow).where(SessionRow.token_hash == token_hash))
    session_row = result.scalar_one_or_none()
    if session_row is None or session_row.expires_at < dt.datetime.now(dt.timezone.utc):
        raise AuthRequiredError()

    user_result = await control_db.execute(
        select(User).where(User.id == session_row.user_id, User.is_active.is_(True))
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise AuthRequiredError()

    # Stashed so get_active_tenant / logout / tenant-switch routes can reuse
    # the row already fetched here without a second query, and so exception
    # handlers (which run outside the dependency graph) can still tell who
    # was asking.
    request.state.session_row = session_row

    current_user = CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role_key=user.role_key,
        home_tenant_id=user.tenant_id,
    )
    request.state.current_user = current_user
    return current_user


async def get_current_user_optional(
    request: Request, control_db: AsyncSession = Depends(get_control_db)
) -> CurrentUser | None:
    try:
        return await get_current_user(request, control_db)
    except AuthRequiredError:
        return None


async def get_active_tenant(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    control_db: AsyncSession = Depends(get_control_db),
) -> Tenant | None:
    """`client` users are pinned to their one tenant. `internal_admin` users
    carry their current selection on the session row (set by the tenant
    switcher) and may have none selected yet."""
    if not user.is_internal_admin:
        if user.home_tenant_id is None:
            return None
        return await control_db.get(Tenant, user.home_tenant_id)

    session_row: SessionRow | None = getattr(request.state, "session_row", None)
    if session_row is None or session_row.active_tenant_id is None:
        return None
    return await control_db.get(Tenant, session_row.active_tenant_id)


async def require_active_tenant(tenant: Tenant | None = Depends(get_active_tenant)) -> Tenant:
    if tenant is None:
        raise TenantRequiredError()
    return tenant


async def get_tenant_db(tenant: Tenant = Depends(require_active_tenant)) -> AsyncSession:
    async with tenant_session(tenant.schema_name) as session:
        yield session


async def get_request_context(
    user: CurrentUser = Depends(get_current_user),
    control_db: AsyncSession = Depends(get_control_db),
    tenant: Tenant | None = Depends(get_active_tenant),
) -> RequestContext:
    return RequestContext(user=user, control_db=control_db, active_tenant=tenant)
