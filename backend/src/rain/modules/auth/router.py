from __future__ import annotations

import datetime as dt
import logging
import re
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.config_store import config_store
from rain.core.security import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    hash_password,
    hash_reset_token,
    hash_session_token,
    new_reset_token,
    new_session_token,
)
from rain.core.tenancy import CurrentUser, get_current_user_optional
from rain.db.base import control_session
from rain.db.control_models import PasswordResetToken, Session as SessionRow, Tenant, User
from rain.modules.auth.provider import authenticate_user
from rain.modules.auth.saml_config import get_saml_config
from rain.modules.auth.saml_provider import build_auth, extract_identity, metadata_xml, provision_user
# The app's one SMTP-sending function lives under tickets.notifications
# (it's where email delivery was first needed) but is generic -- reused
# here rather than duplicating the aiosmtplib/config_store plumbing for
# a second email-sending code path that could drift from the first.
from rain.modules.tickets.notifications import send_email
from rain.web.safe_redirect import public_origin, safe_relative_path
from rain.web.templating import templates

logger = logging.getLogger("rain.auth")

router = APIRouter(tags=["Auth"])

# A reset link is only valid for an hour -- long enough to find the email,
# short enough that a link sitting in an old inbox isn't a standing risk.
RESET_TOKEN_TTL_SECONDS = 60 * 60

# Same pattern browsers use to validate a bare <input type="email"> (the
# WHATWG HTML living standard's "willful violation" of RFC 5322 -- covers
# every punctuation character actually seen in real addresses in the
# local part: . ! # $ % & ' * + / = ? ^ _ ` { | } ~ - , without the full
# RFC's quoted-string/comment/IP-literal grammar nobody's inbox actually
# uses). login.html's email field used to be type="email" and relied on
# the browser to enforce this client-side -- moved server-side instead
# (see login_submit) so a malformed address gets an explicit "Not a
# valid email address" instead of the browser silently refusing to
# submit the form at all with no message shown anywhere.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


def _is_valid_email_format(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


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

    # Stamped here rather than in authenticate_user/the SAML provider so
    # every successful sign-in updates it exactly once, in the one place
    # both paths already converge -- backs Admin > Users' "Last login"
    # column and CSV export (see migration 0010's own docstring for the
    # access-review reasoning).
    user.last_login_at = dt.datetime.now(dt.timezone.utc)

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
        {
            "error": None,
            "next": request.query_params.get("next", "/"),
            "saml_enabled": saml_enabled,
            "smtp_configured": bool(config_store.get("smtp_host")),
            "reset": request.query_params.get("reset"),
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    async with control_session() as session:
        # Checked before ever touching the DB -- a malformed address can
        # never match a User row anyway, but "Invalid email or password"
        # for e.g. "tewrwer" reads as if the account might just not
        # exist, when the real problem is the address itself isn't one.
        # login.html's email field used to catch this client-side
        # (type="email") before the browser's own silent-refusal-to-
        # submit turned into its own confusing "nothing happened" bug.
        smtp_configured = bool(config_store.get("smtp_host"))
        if not _is_valid_email_format(email):
            saml_enabled = await get_saml_config(session) is not None
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": "Not a valid email address.",
                    "next": next,
                    "saml_enabled": saml_enabled,
                    "smtp_configured": smtp_configured,
                    "reset": None,
                },
                status_code=400,
            )
        user = await authenticate_user(session, email, password)
        if user is None:
            saml_enabled = await get_saml_config(session) is not None
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": "Invalid email or password.",
                    "next": next,
                    "saml_enabled": saml_enabled,
                    "smtp_configured": smtp_configured,
                    "reset": None,
                },
                status_code=400,
            )
        return await _issue_session(request, session, user, next)


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_form(request: Request, user: CurrentUser | None = Depends(get_current_user_optional)):
    if user is not None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {"error": None, "sent": False, "smtp_configured": bool(config_store.get("smtp_host"))},
    )


@router.post("/forgot-password")
async def forgot_password_submit(request: Request, email: str = Form(...)):
    # Mirrors login_form's own guard: someone reaching this route while
    # SMTP isn't configured (the link is hidden on login.html in that
    # case, but nothing stops a direct POST) gets told plainly rather
    # than a silent no-op that looks like an email was sent.
    if not config_store.get("smtp_host"):
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": "Password reset isn't available on this instance -- contact your administrator.", "sent": False, "smtp_configured": False},
            status_code=400,
        )
    if not _is_valid_email_format(email):
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": "Not a valid email address.", "sent": False, "smtp_configured": True},
            status_code=400,
        )

    async with control_session() as session:
        result = await session.execute(
            select(User).where(
                User.email == email.strip().lower(), User.auth_source == "local", User.is_active.is_(True)
            )
        )
        user = result.scalar_one_or_none()
        if user is not None:
            # Clear any earlier, still-unused request first -- otherwise
            # an old emailed link stays live alongside a freshly
            # requested one instead of being superseded by it.
            await session.execute(
                delete(PasswordResetToken).where(
                    PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
                )
            )
            token = new_reset_token()
            session.add(
                PasswordResetToken(
                    token_hash=hash_reset_token(token),
                    user_id=user.id,
                    expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=RESET_TOKEN_TTL_SECONDS),
                )
            )
            await session.commit()
            reset_url = f"{public_origin(request)}/reset-password?token={token}"
            await send_email(
                [user.email],
                "Reset your RAIN password",
                "A password reset was requested for your RAIN account.\n\n"
                f"Reset your password: {reset_url}\n\n"
                "This link expires in 1 hour and can only be used once. "
                "If you didn't request this, you can safely ignore this email.",
            )
        # Same response whether or not that email matched a real local
        # account -- a different one here would let this form be used to
        # test which email addresses have accounts (or which ones are
        # LDAP/SAML-only and so have no local password to reset).

    return templates.TemplateResponse(
        request, "forgot_password.html", {"error": None, "sent": True, "smtp_configured": True}
    )


async def _valid_reset_token(session: AsyncSession, token: str) -> PasswordResetToken | None:
    if not token:
        return None
    result = await session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_reset_token(token))
    )
    reset = result.scalar_one_or_none()
    if reset is None or reset.used_at is not None:
        return None
    if reset.expires_at < dt.datetime.now(dt.timezone.utc):
        return None
    return reset


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_form(request: Request, token: str = ""):
    async with control_session() as session:
        reset = await _valid_reset_token(session, token)
    return templates.TemplateResponse(
        request, "reset_password.html", {"token": token, "valid": reset is not None, "error": None}
    )


@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    async with control_session() as session:
        reset = await _valid_reset_token(session, token)
        if reset is None:
            return templates.TemplateResponse(
                request,
                "reset_password.html",
                {"token": token, "valid": False, "error": None},
                status_code=400,
            )
        if new_password != confirm_password:
            return templates.TemplateResponse(
                request,
                "reset_password.html",
                {"token": token, "valid": True, "error": "Passwords don't match."},
                status_code=400,
            )
        # Same 10-character minimum enforced at account creation
        # (setup/router.py) and admin-initiated password changes
        # (admin/router.py) -- kept identical rather than inventing a
        # separate policy for this one entry point.
        if len(new_password) < 10:
            return templates.TemplateResponse(
                request,
                "reset_password.html",
                {"token": token, "valid": True, "error": "Password must be at least 10 characters."},
                status_code=400,
            )

        user_result = await session.execute(select(User).where(User.id == reset.user_id))
        user = user_result.scalar_one()
        user.password_hash = hash_password(new_password)
        reset.used_at = dt.datetime.now(dt.timezone.utc)
        # A password reset is exactly the moment an account might just
        # have been recovered from someone else's control -- any session
        # still live at that point (on any device) shouldn't survive it.
        await session.execute(delete(SessionRow).where(SessionRow.user_id == user.id))
        await session.commit()

    return RedirectResponse("/login?reset=1", status_code=status.HTTP_303_SEE_OTHER)


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
        logger.warning("SAML SSO: login attempt with no SAML config present -- redirected to /login")
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    auth = await build_auth(request, config)
    redirect_url = auth.login(return_to=next)
    logger.info("SAML SSO: login initiated -- idp=%s next=%s", config.idp_entity_id, next)
    return RedirectResponse(redirect_url, status_code=status.HTTP_302_FOUND)


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
            logger.warning("SAML ACS: response received but no SAML config present -- redirected to /login")
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

        auth = await build_auth(request, config)
        # No request_id: RAIN doesn't track outbound AuthnRequest IDs
        # server-side (stateless -- no session to stash one in until this
        # exact call mints one), so this doesn't check InResponseTo and
        # accepts IdP-initiated SSO too, not only responses to a request
        # RAIN itself sent. The signature check below is what actually
        # matters for trusting the response's contents either way.
        try:
            auth.process_response()
        except Exception:
            # process_response() raises rather than populating get_errors()
            # for some malformed input (confirmed live: a SAMLResponse that
            # isn't valid base64-encoded XML at all raises lxml.etree.
            # XMLSyntaxError deep inside python3-saml) -- caught here so a
            # misconfigured IdP (wrong encoding, wrong binding, posting the
            # wrong field) gets the same graceful "SSO sign-in failed" page
            # everything else in this function does, instead of a bare 500.
            logger.exception("SAML ACS: process_response() raised -- malformed SAMLResponse?")
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "SSO sign-in failed: malformed response.", "next": "/", "saml_enabled": True},
                status_code=400,
            )
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
        # Logged before provisioning even runs: if provision_user
        # rejects the identity below (no email, or an email collision),
        # this line is what shows *what the assertion actually carried* --
        # the two warnings it can log don't repeat the raw attribute values.
        logger.info(
            "SAML ACS: assertion accepted -- subject=%s email=%s role_attr=%s (admin value configured: %s)",
            identity.subject,
            identity.email,
            identity.role_attribute_value,
            config.role_admin_value,
        )
        user = await provision_user(session, config, identity)
        if user is None:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "SSO sign-in failed: no usable account for this identity.", "next": "/", "saml_enabled": True},
                status_code=400,
            )
        if not user.is_active:
            logger.warning("SAML ACS: %s resolved to a deactivated account -- refused", user.email)
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "This account is deactivated.", "next": "/", "saml_enabled": True},
                status_code=400,
            )

        form = await request.form()
        next_path = str(form.get("RelayState") or "/")
        logger.info(
            "SAML ACS: session issued for %s (role=%s, tenant_id=%s) -> %s",
            user.email,
            user.role_key,
            user.tenant_id,
            next_path,
        )
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
