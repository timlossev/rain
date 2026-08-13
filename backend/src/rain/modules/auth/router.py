from __future__ import annotations

import datetime as dt
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select

from rain.core.security import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    hash_session_token,
    new_session_token,
)
from rain.core.tenancy import CurrentUser, get_current_user_optional
from rain.db.base import control_session
from rain.db.control_models import Session as SessionRow, Tenant, User
from rain.modules.auth.provider import authenticate_user
from rain.web.templating import templates

router = APIRouter()


def _safe_next(path: str) -> str:
    if path.startswith("/") and not path.startswith("//"):
        return path
    return "/"


async def _hinted_tenant_id(session, next_path: str, user: User) -> int | None:
    """A deep link into the app can carry ?tenant=<slug> so that, after
    signing in, an internal_admin lands with that tenant already active
    instead of whatever they last had selected (or none) -- see
    rain.main's auth_required_handler, which is what actually gets a bare
    /tickets/123 link here with the hint intact.

    Deliberately internal_admin only: a client user is hard-pinned to their
    own tenant_id (below) regardless of this hint, so a crafted
    ?tenant=<other slug> can never move a client session into a tenant they
    don't already belong to -- the lookup here isn't even attempted for
    them. This does not resolve or reveal anything about the linked
    resource itself (e.g. no ticket number) before authentication --
    doing that would mean querying a tenant schema keyed off unauthenticated
    input, which is a cross-tenant enumeration risk this deliberately avoids."""
    if user.role_key != "internal_admin":
        return None
    query = parse_qs(urlsplit(next_path).query)
    slugs = query.get("tenant")
    if not slugs:
        return None
    result = await session.execute(select(Tenant).where(Tenant.slug == slugs[0], Tenant.is_active.is_(True)))
    tenant = result.scalar_one_or_none()
    return tenant.id if tenant else None


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, user: CurrentUser | None = Depends(get_current_user_optional)):
    if user is not None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request, "login.html", {"error": None, "next": request.query_params.get("next", "/")}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    async with control_session() as session:
        user = await authenticate_user(session, email, password)
        if user is None:
            return templates.TemplateResponse(
                request, "login.html", {"error": "Invalid email or password.", "next": next}, status_code=400
            )

        hinted_tenant_id = await _hinted_tenant_id(session, next, user)

        token = new_session_token()
        session.add(
            SessionRow(
                token_hash=hash_session_token(token),
                user_id=user.id,
                active_tenant_id=hinted_tenant_id if hinted_tenant_id is not None else user.tenant_id,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=SESSION_TTL_SECONDS),
            )
        )
        await session.commit()

    response = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE_NAME, token, max_age=SESSION_TTL_SECONDS, httponly=True, samesite="lax", secure=True
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        async with control_session() as session:
            await session.execute(delete(SessionRow).where(SessionRow.token_hash == hash_session_token(token)))
            await session.commit()

    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
