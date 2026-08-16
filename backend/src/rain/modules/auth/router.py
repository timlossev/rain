from __future__ import annotations

import datetime as dt
import logging
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from rain.modules.auth.saml_config import get_saml_config
from rain.modules.auth.saml_provider import build_auth, extract_identity, metadata_xml, provision_or_update_user
from rain.web.safe_redirect import safe_relative_path
from rain.web.templating import templates

logger = logging.getLogger("rain.auth")

router = APIRouter(tags=["Auth"])


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


async def _issue_session(
    request: Request, session: AsyncSession, user: User, next_path: str
) -> RedirectResponse:
    """Shared by local-password login and the SAML ACS handler -- from this
    point on, however the user got authenticated, a session is a session."""
    hinted_tenant_id = await _hinted_tenant_id(session, next_path, user)

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

    response = RedirectResponse(safe_relative_path(next_path), status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE_NAME, token, max_age=SESSION_TTL_SECONDS, httponly=True, samesite="lax", secure=True
    )
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, user: CurrentUser | None = Depends(get_current_user_optional)):
    if user is not None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    async with control_session() as session:
        saml_enabled = await get_saml_config(session) is not None
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": None, "next": request.query_params.get("next", "/"), "saml_enabled": saml_enabled},
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
            saml_enabled = await get_saml_config(session) is not None
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Invalid email or password.", "next": next, "saml_enabled": saml_enabled},
                status_code=400,
            )
        return await _issue_session(request, session, user, next)


@router.get("/auth/saml/metadata")
async def saml_metadata(request: Request):
    """Public, unauthenticated -- SP metadata for the IdP side of setup
    (most IdPs can import this URL directly instead of hand-entering the
    SP entity ID / ACS URL). 404s rather than 500s if SAML isn't
    configured yet -- no config to build metadata from."""
    async with control_session() as session:
        config = await get_saml_config(session)
    if config is None:
        return PlainTextResponse("SAML is not configured.", status_code=404)
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    xml, errors = metadata_xml(config, base_url)
    if errors:
        logger.error("SAML SP metadata invalid: %s", errors)
        return PlainTextResponse(f"Invalid SP metadata: {errors}", status_code=500)
    return Response(content=xml, media_type="application/xml")


@router.get("/auth/saml/login")
async def saml_login(request: Request, next: str = "/"):
    async with control_session() as session:
        config = await get_saml_config(session)
    if config is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    auth = await build_auth(request, config)
    return RedirectResponse(auth.login(return_to=next), status_code=status.HTTP_302_FOUND)


@router.post("/auth/saml/acs")
async def saml_acs(request: Request):
    """Assertion Consumer Service -- where the IdP POSTs the SAMLResponse
    after authenticating the user. process_response() is where python3-
    saml actually verifies the assertion's XML signature against the
    configured IdP certificate; nothing past that point is trusted until
    it returns cleanly with no errors."""
    async with control_session() as session:
        config = await get_saml_config(session)
        if config is None:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

        auth = await build_auth(request, config)
        # No request_id: RAIN doesn't track outbound AuthnRequest IDs
        # server-side (stateless -- no session to stash one in until this
        # exact call mints one), so this doesn't check InResponseTo and
        # accepts IdP-initiated SSO too, not only responses to a request
        # RAIN itself sent. The signature check below is what actually
        # matters for trusting the response's contents either way.
        auth.process_response()
        errors = auth.get_errors()
        if errors or not auth.is_authenticated():
            logger.warning("SAML ACS: rejected -- %s (%s)", errors, auth.get_last_error_reason())
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "SSO sign-in failed.", "next": "/", "saml_enabled": True},
                status_code=400,
            )

        identity = extract_identity(auth, config)
        user = await provision_or_update_user(session, config, identity)
        if user is None:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "SSO sign-in failed: no usable account for this identity.", "next": "/", "saml_enabled": True},
                status_code=400,
            )
        if not user.is_active:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "This account is deactivated.", "next": "/", "saml_enabled": True},
                status_code=400,
            )

        form = await request.form()
        next_path = str(form.get("RelayState") or "/")
        return await _issue_session(request, session, user, next_path)


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
