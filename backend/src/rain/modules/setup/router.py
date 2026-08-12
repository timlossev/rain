"""First-run setup wizard. Blocks the rest of the app (see the middleware
in rain.main) until `global_config.setup_complete` is true. Captures the
instance's only unavoidable bootstrap facts: branding, the first
internal_admin, and the first tenant -- everything else stays configurable
at runtime afterwards."""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from rain.core.config_store import config_store
from rain.core.security import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    hash_password,
    hash_session_token,
    new_session_token,
)
from rain.db.base import control_session
from rain.db.control_models import Session as SessionRow
from rain.db.control_models import User
from rain.db.provisioning import InvalidSlugError, provision_tenant
from rain.web.templating import templates
from rain.web.uploads import UploadError, save_logo_upload

router = APIRouter()
logger = logging.getLogger("rain.setup")


async def setup_already_done() -> bool:
    if config_store.get("setup_complete", False):
        return True
    async with control_session() as session:
        result = await session.execute(select(User.id).where(User.role_key == "internal_admin"))
        return result.first() is not None


@router.get("/setup", response_class=HTMLResponse)
async def setup_form(request: Request):
    if await setup_already_done():
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "setup.html", {"error": None})


@router.post("/setup")
async def setup_submit(
    request: Request,
    instance_name: str = Form(...),
    accent_color: str = Form("#6366f1"),
    tenant_name: str = Form(...),
    tenant_slug: str = Form(...),
    admin_email: str = Form(...),
    admin_name: str = Form(...),
    admin_password: str = Form(...),
    logo: UploadFile | None = None,
):
    if await setup_already_done():
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    if len(admin_password) < 10:
        return templates.TemplateResponse(
            request, "setup.html", {"error": "Password must be at least 10 characters."}, status_code=400
        )

    try:
        tenant = await provision_tenant(slug=tenant_slug.strip().lower(), name=tenant_name.strip())
    except InvalidSlugError as exc:
        return templates.TemplateResponse(request, "setup.html", {"error": str(exc)}, status_code=400)

    try:
        async with control_session() as session:
            admin = User(
                tenant_id=None,
                email=admin_email.strip().lower(),
                password_hash=hash_password(admin_password),
                role_key="internal_admin",
                display_name=admin_name.strip(),
            )
            session.add(admin)
            await session.flush()

            token = new_session_token()
            session.add(
                SessionRow(
                    token_hash=hash_session_token(token),
                    user_id=admin.id,
                    active_tenant_id=tenant.id,
                    expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=SESSION_TTL_SECONDS),
                )
            )
            await session.commit()

        logo_path = None
        if logo is not None and logo.filename:
            try:
                logo_path = await save_logo_upload(logo)
            except UploadError:
                logo_path = None  # branding can always be fixed later in Admin

        await config_store.set("instance_name", instance_name.strip())
        await config_store.set("accent_color", accent_color)
        if logo_path:
            await config_store.set("logo_path", logo_path)
        await config_store.set("setup_complete", True)

        response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            SESSION_COOKIE_NAME, token, max_age=SESSION_TTL_SECONDS, httponly=True, samesite="lax", secure=True
        )
        return response
    except Exception:
        logger.exception("setup_submit failed after provisioning tenant %r", tenant.slug)
        raise
