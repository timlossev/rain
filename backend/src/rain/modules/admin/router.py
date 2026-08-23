"""Admin console: two tiers, split by which RBAC dependency each route
uses (see rain.core.rbac). Tenants/Users/Auth Providers/SMTP Relay/
Syslog Listener are platform-wide (require_internal_admin only).
Branding's GET is require_admin -- client_admin can reach the page too,
but only sees and can save the public-incident-portal section for their
own tenant; its instance-wide name/color/logo/font stays
internal_admin-only, both hidden in the template and enforced on its own
POST route. Ticket Statuses/Notification Channels/Groups/Approval Flows/
Webhooks are the same require_admin tier (internal_admin for whichever
tenant is active, or client_admin for their one pinned tenant; Event
Promotion Policies/Platform Response Rules are the same tier but live in
rain.modules.tickets.router instead, alongside the rest of Tickets)."""
from __future__ import annotations

import asyncio
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.core import ldap_client
from rain.core.config_store import FONT_CHOICES, config_store
from rain.core.crypto import decrypt_json, encrypt_json
from rain.core.pagination import paginate
from rain.core.rbac import require_admin, require_internal_admin, require_login
from rain.core.security import hash_password
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.core.tenant_config import get_tenant_config, get_tenant_configs, set_tenant_config, set_tenant_configs
from rain.core.url_safety import check_outbound_url
from rain.core.user_names import is_assignable_user, resolve_user_names
from rain.db.base import control_session, tenant_session
from rain.db.control_models import AuthProviderConfig, Session as SessionRow, SyslogSourceMap, Tenant, User
from rain.db.provisioning import InvalidSlugError, provision_tenant
from rain.db.tenant_models import (
    ApprovalFlow,
    ApprovalFlowStep,
    Group,
    GroupMembership,
    NotificationChannel,
    ServiceCatalogItem,
    TicketStatus,
    WebhookConfig,
)
from rain.modules.auth import saml_config
from rain.modules.auth.ldap_config import get_provider_row, get_raw_config, save_ldap_config
from rain.modules.auth.ldap_sync import run_ldap_sync
from rain.modules.catalog import service as catalog_service
from rain.modules.catalog.schemas import MAX_CATALOG_FIELDS, PAYLOAD_FORMATS, SOURCE_MODES
from rain.modules.tickets import notifications
from rain.modules.tickets.schemas import CHANNEL_TYPES, SEVERITIES, TICKET_TYPES
from rain.modules.webhooks import service as webhook_service
from rain.settings import get_settings
from rain.web.nav import build_nav_context
from rain.web.templating import templates
from rain.web.uploads import UploadError, save_logo_upload, save_portal_background_upload

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request, ctx: RequestContext = Depends(get_request_context), _: CurrentUser = Depends(require_login)
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "admin/dashboard.html", {**nav, "ctx": ctx})


async def _portal_settings(ctx: RequestContext) -> dict:
    """The incident portal's per-tenant flags (rain.modules.portal) plus
    the tenant's escalation webhook (rain.modules.tickets.service.
    escalate_ticket) -- scoped to whichever tenant is currently active,
    same "mixed platform-wide + active-tenant" page shape Admin > Syslog
    Listener already uses for its retention setting. Falls back to the
    (locked-down) defaults with no tenant_session at all when no tenant
    is active, rather than making one a hard requirement to even view
    this page -- unlike every *other* tenant-scoped admin screen,
    Branding has to stay reachable for an internal_admin who hasn't
    picked a tenant yet, since it's also where instance-wide branding
    lives."""
    if ctx.active_tenant is None:
        return {
            "portal_require_auth": True,
            "portal_branded": True,
            "escalation_webhook_id": None,
            "portal_tenant": None,
            "webhooks": [],
        }
    async with tenant_session(ctx.active_tenant.schema_name) as tenant_db:
        flags = await get_tenant_configs(
            tenant_db, ["portal_require_auth", "portal_branded", "escalation_webhook_id"]
        )
        webhooks = list((await tenant_db.execute(select(WebhookConfig).order_by(WebhookConfig.name))).scalars())
        return {**flags, "portal_tenant": ctx.active_tenant, "webhooks": webhooks}


@router.get("/branding", response_class=HTMLResponse)
async def branding_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(
        request,
        "admin/branding.html",
        {**nav, "ctx": ctx, "error": None, "font_choices": FONT_CHOICES, **await _portal_settings(ctx)},
    )


@router.post("/branding")
async def branding_submit(
    request: Request,
    instance_name: str = Form(...),
    accent_color: str = Form(...),
    font_family: str = Form(""),
    logo: UploadFile | None = None,
    portal_background: UploadFile | None = None,
    ctx: RequestContext = Depends(get_request_context),
    user: CurrentUser = Depends(require_internal_admin),
):
    async def _error(exc: UploadError) -> HTMLResponse:
        nav = await build_nav_context(ctx)
        return templates.TemplateResponse(
            request,
            "admin/branding.html",
            {**nav, "ctx": ctx, "error": str(exc), "font_choices": FONT_CHOICES, **await _portal_settings(ctx)},
            status_code=400,
        )

    await config_store.set("instance_name", instance_name.strip(), updated_by=user.id)
    await config_store.set("accent_color", accent_color.strip(), updated_by=user.id)
    # Whitelisted against FONT_CHOICES (not just server-rendered <select>
    # options) since the stored value is injected into base.html's <style>
    # block with the `safe` filter -- an arbitrary POST body must not be
    # able to smuggle CSS/HTML through it.
    allowed_fonts = {css for _, css in FONT_CHOICES}
    if font_family in allowed_fonts:
        await config_store.set("font_family", font_family, updated_by=user.id)
    if logo is not None and logo.filename:
        try:
            logo_path = await save_logo_upload(logo)
            await config_store.set("logo_path", logo_path, updated_by=user.id)
        except UploadError as exc:
            return await _error(exc)
    # Optional -- the client portal renders exactly as it does today
    # (branding.portal_background_path is None, same as before this
    # field existed) until an internal_admin sets one here.
    if portal_background is not None and portal_background.filename:
        try:
            background_path = await save_portal_background_upload(portal_background)
            await config_store.set("portal_background_path", background_path, updated_by=user.id)
        except UploadError as exc:
            return await _error(exc)
    return RedirectResponse("/admin/branding?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/branding/portal")
async def branding_portal_submit(
    portal_require_auth: bool = Form(False),
    portal_branded: bool = Form(False),
    escalation_webhook_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    user: CurrentUser = Depends(require_admin),
):
    """Saves rain.modules.portal's per-tenant flags, plus the escalation
    webhook, for whichever tenant is currently active. A no-op (not an
    error) with no active tenant -- there's nothing to save into --
    since the page that posts here already hides this form in that case
    rather than blocking the whole Branding screen on picking one
    first."""
    if ctx.active_tenant is not None:
        async with tenant_session(ctx.active_tenant.schema_name) as tenant_db:
            await set_tenant_configs(
                tenant_db,
                {
                    "portal_require_auth": portal_require_auth,
                    "portal_branded": portal_branded,
                    "escalation_webhook_id": int(escalation_webhook_id) if escalation_webhook_id else None,
                },
                updated_by=user.id,
            )
    return RedirectResponse("/admin/branding?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/tenants", response_class=HTMLResponse)
async def tenants_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        stmt = select(Tenant).order_by(Tenant.name)
        tenant_page = await paginate(session, stmt, page=page)
    return templates.TemplateResponse(
        request, "admin/tenants.html", {**nav, "ctx": ctx, "page": tenant_page, "error": None}
    )


@router.post("/tenants")
async def tenants_create(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    try:
        await provision_tenant(slug=slug.strip().lower(), name=name.strip())
    except InvalidSlugError as exc:
        nav = await build_nav_context(ctx)
        async with control_session() as session:
            stmt = select(Tenant).order_by(Tenant.name)
            tenant_page = await paginate(session, stmt, page=1)
        return templates.TemplateResponse(
            request,
            "admin/tenants.html",
            {**nav, "ctx": ctx, "page": tenant_page, "error": str(exc)},
            status_code=400,
        )
    return RedirectResponse("/admin/tenants", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tenants/switch")
async def switch_tenant(request: Request, tenant_id: int = Form(...), _: CurrentUser = Depends(require_internal_admin)):
    session_row: SessionRow = request.state.session_row
    async with control_session() as session:
        row = await session.get(SessionRow, session_row.id)
        if row is not None:
            row.active_tenant_id = tenant_id
            await session.commit()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        stmt = select(User).options(selectinload(User.tenant)).order_by(User.email)
        user_page = await paginate(session, stmt, page=page)
        tenants = list((await session.execute(select(Tenant).order_by(Tenant.name))).scalars())
    return templates.TemplateResponse(
        request, "admin/users.html", {**nav, "ctx": ctx, "page": user_page, "tenants": tenants, "error": None}
    )


@router.post("/users")
async def users_create(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    role_key: str = Form(...),
    tenant_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    if role_key in ("client", "client_admin") and not tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Client users must be assigned a tenant.")

    async with control_session() as session:
        session.add(
            User(
                email=email.strip().lower(),
                display_name=display_name.strip(),
                password_hash=hash_password(password),
                role_key=role_key,
                tenant_id=int(tenant_id) if tenant_id else None,
            )
        )
        await session.commit()
    return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id:int}/deactivate")
async def deactivate_user(user_id: int, _: CurrentUser = Depends(require_internal_admin)):
    async with control_session() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.is_active = False
            await session.commit()
    return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users/{user_id:int}/edit", response_class=HTMLResponse)
async def edit_user_form(
    request: Request,
    user_id: int,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)
        tenants = list((await session.execute(select(Tenant).order_by(Tenant.name))).scalars())
        return templates.TemplateResponse(
            request, "admin/user_edit.html", {**nav, "ctx": ctx, "edit_user": user, "tenants": tenants, "error": None}
        )


@router.post("/users/{user_id:int}")
async def update_user(
    request: Request,
    user_id: int,
    display_name: str = Form(...),
    role_key: str = Form(...),
    tenant_id: str = Form(""),
    password: str = Form(""),
    is_active: bool = Form(False),
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    if role_key in ("client", "client_admin") and not tenant_id:
        nav = await build_nav_context(ctx)
        async with control_session() as session:
            user = await session.get(User, user_id)
            tenants = list((await session.execute(select(Tenant).order_by(Tenant.name))).scalars())
            return templates.TemplateResponse(
                request,
                "admin/user_edit.html",
                {
                    **nav,
                    "ctx": ctx,
                    "edit_user": user,
                    "tenants": tenants,
                    "error": "Client users must be assigned a tenant.",
                },
                status_code=400,
            )

    async with control_session() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.display_name = display_name.strip()
            user.role_key = role_key
            user.tenant_id = int(tenant_id) if tenant_id else None
            user.is_active = is_active
            if password.strip():
                user.password_hash = hash_password(password.strip())
            await session.commit()
    return RedirectResponse("/admin/users?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/smtp", response_class=HTMLResponse)
async def smtp_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "admin/smtp.html", {**nav, "ctx": ctx})


@router.post("/smtp")
async def smtp_submit(
    smtp_host: str = Form(""),
    smtp_port: int = Form(587),
    smtp_username: str = Form(""),
    smtp_password: str = Form(""),
    smtp_from_address: str = Form(""),
    smtp_use_tls: bool = Form(False),
    user: CurrentUser = Depends(require_internal_admin),
):
    await config_store.set("smtp_host", smtp_host.strip(), updated_by=user.id)
    await config_store.set("smtp_port", smtp_port, updated_by=user.id)
    await config_store.set("smtp_username", smtp_username.strip(), updated_by=user.id)
    await config_store.set("smtp_from_address", smtp_from_address.strip(), updated_by=user.id)
    await config_store.set("smtp_use_tls", smtp_use_tls, updated_by=user.id)
    if smtp_password:
        # Only overwritten when a new password is actually typed in --
        # the form never shows the existing one back.
        await config_store.set("smtp_password_encrypted", encrypt_json(smtp_password).hex(), updated_by=user.id)
    return RedirectResponse("/admin/smtp?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/smtp/test")
async def smtp_test(
    smtp_host: str = Form(""),
    smtp_port: int = Form(587),
    smtp_username: str = Form(""),
    smtp_password: str = Form(""),
    smtp_from_address: str = Form(""),
    smtp_use_tls: bool = Form(False),
    test_recipient: str = Form(""),
    _: CurrentUser = Depends(require_internal_admin),
):
    """"Send test email" -- the same form's fields, submitted here instead
    of /admin/smtp via the button's formaction, so this tests exactly
    what's currently typed in rather than whatever was last saved
    (nothing here is written to config_store). A blank password field
    means "use whatever's already saved" here too, same convention as
    the real save route just above -- most of the time an admin testing
    an already-configured relay isn't retyping the password just to
    click this button."""
    if not smtp_host.strip():
        return RedirectResponse("/admin/smtp?test_error=Host+is+required.", status_code=status.HTTP_303_SEE_OTHER)
    if not test_recipient.strip():
        return RedirectResponse(
            "/admin/smtp?test_error=Enter+an+address+to+send+the+test+to.", status_code=status.HTTP_303_SEE_OTHER
        )

    password = smtp_password
    if not password and smtp_username.strip():
        encrypted_password = config_store.get("smtp_password_encrypted")
        password = decrypt_json(bytes.fromhex(encrypted_password)) if encrypted_password else ""

    ok, detail = await notifications.send_test_email(
        host=smtp_host.strip(),
        port=smtp_port,
        username=smtp_username.strip(),
        password=password,
        use_tls=smtp_use_tls,
        from_address=smtp_from_address.strip(),
        to_address=test_recipient.strip(),
    )
    param = "test_ok" if ok else "test_error"
    return RedirectResponse(f"/admin/smtp?{param}={quote(detail)}", status_code=status.HTTP_303_SEE_OTHER)


async def _listener_is_active(port: int) -> bool:
    """A real-time up/down check rather than a cached/assumed status --
    opens (and immediately closes) a TCP connection to the syslog
    listener, same idea as that container's own Docker healthcheck.

    Which host to check depends on the deployment shape: normally the
    listener runs in the separate `worker` container, reachable from
    `app` over the compose network by that service name; with
    EMBED_WORKER=true (single-container/minimal mode, see
    rain.worker_runtime) it runs in this exact same process instead, so
    there's no "worker" hostname to resolve on any network -- it has to
    check its own loopback. Confirmed live: checking "worker"
    unconditionally in that mode always fails DNS resolution regardless
    of whether the listener is actually up, showing the port as
    permanently "down" in the UI even while a manual telnet to it from
    outside the container succeeded fine. A closed/refused/timed-out
    connection just means "down", not an error to surface."""
    host = "localhost" if get_settings().embed_worker else "worker"
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.5)
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


@router.get("/syslog-sources", response_class=HTMLResponse)
async def syslog_sources_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    listener_port = get_settings().syslog_port
    async with control_session() as session:
        stmt = (
            select(SyslogSourceMap)
            .options(selectinload(SyslogSourceMap.tenant))
            .order_by(SyslogSourceMap.sort_order)
        )
        source_page = await paginate(session, stmt, page=page)
        tenants = list((await session.execute(select(Tenant).order_by(Tenant.name))).scalars())
    retention_hours = await get_tenant_config(tenant_db, "event_retention_hours", 12)
    return templates.TemplateResponse(
        request,
        "admin/syslog_sources.html",
        {
            **nav,
            "ctx": ctx,
            "page": source_page,
            "tenants": tenants,
            "listener_port": listener_port,
            "listener_active": await _listener_is_active(listener_port),
            "retention_hours": retention_hours,
        },
    )


@router.post("/syslog-sources/retention")
async def syslog_sources_retention_save(
    retention_hours: float = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_internal_admin),
):
    """How long an "untreated" syslog event (never promoted into a
    ticket) stays around before rain.modules.tickets.listener.
    run_retention_sweep deletes it, for the currently active tenant --
    TenantConfig is per-tenant-schema, same as every other setting on
    this page's active-tenant scope."""
    await set_tenant_config(tenant_db, "event_retention_hours", max(0.5, retention_hours), updated_by=ctx.user.id)
    return RedirectResponse("/admin/syslog-sources?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/syslog-sources")
async def syslog_sources_create(
    action: str = Form("route"),
    tenant_id: str = Form(""),  # required for action=route, ignored/blank for action=discard
    match_field: str = Form(...),
    pattern: str = Form(...),
    is_regex: bool = Form(False),
    sort_order: int = Form(0),
    _: CurrentUser = Depends(require_internal_admin),
):
    action = action if action == "discard" else "route"
    async with control_session() as session:
        session.add(
            SyslogSourceMap(
                tenant_id=int(tenant_id) if action == "route" and tenant_id else None,
                match_field=match_field,
                pattern=pattern.strip(),
                is_regex=is_regex,
                action=action,
                sort_order=sort_order,
            )
        )
        await session.commit()
    return RedirectResponse("/admin/syslog-sources", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/syslog-sources/{source_id:int}/edit")
async def syslog_sources_edit(
    source_id: int,
    action: str = Form("route"),
    tenant_id: str = Form(""),
    match_field: str = Form(...),
    pattern: str = Form(...),
    is_regex: bool = Form(False),
    sort_order: int = Form(0),
    _: CurrentUser = Depends(require_internal_admin),
):
    action = action if action == "discard" else "route"
    async with control_session() as session:
        row = await session.get(SyslogSourceMap, source_id)
        if row is not None:
            row.action = action
            row.tenant_id = int(tenant_id) if action == "route" and tenant_id else None
            row.match_field = match_field
            row.pattern = pattern.strip()
            row.is_regex = is_regex
            row.sort_order = sort_order
            await session.commit()
    return RedirectResponse("/admin/syslog-sources", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/syslog-sources/{source_id:int}/toggle")
async def syslog_sources_toggle(source_id: int, _: CurrentUser = Depends(require_internal_admin)):
    async with control_session() as session:
        row = await session.get(SyslogSourceMap, source_id)
        if row is not None:
            row.is_active = not row.is_active
            await session.commit()
    return RedirectResponse("/admin/syslog-sources", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/syslog-sources/{source_id:int}/delete")
async def syslog_sources_delete(source_id: int, _: CurrentUser = Depends(require_internal_admin)):
    async with control_session() as session:
        row = await session.get(SyslogSourceMap, source_id)
        if row is not None:
            await session.delete(row)
            await session.commit()
    return RedirectResponse("/admin/syslog-sources", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth-providers", response_class=HTMLResponse)
async def auth_providers_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        providers = list(
            (await session.execute(select(AuthProviderConfig).order_by(AuthProviderConfig.id))).scalars()
        )
    return templates.TemplateResponse(request, "admin/auth_providers.html", {**nav, "ctx": ctx, "providers": providers})


@router.get("/auth-providers/ldap", response_class=HTMLResponse)
async def ldap_config_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        row = await get_provider_row(session)
        config = await get_raw_config(session)
        tenants = list(
            (await session.execute(select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.name))).scalars()
        )
    return templates.TemplateResponse(
        request,
        "admin/auth_provider_ldap.html",
        {
            **nav,
            "ctx": ctx,
            "config": config,
            "tenants": tenants,
            "is_enabled": row.is_enabled if row else False,
            "last_synced_at": row.last_synced_at if row else None,
            "last_sync_summary": row.last_sync_summary if row else None,
            "test_result": request.query_params.get("test_result"),
        },
    )


@router.post("/auth-providers/ldap")
async def ldap_config_save(
    server_uri: str = Form(...),
    use_starttls: bool = Form(False),
    bind_dn: str = Form(...),
    bind_password: str = Form(""),
    user_base_dn: str = Form(...),
    user_filter: str = Form(...),
    user_email_attr: str = Form(...),
    user_name_attr: str = Form(...),
    group_base_dn: str = Form(...),
    group_filter: str = Form(...),
    group_name_attr: str = Form(...),
    group_member_attr: str = Form(...),
    target_tenant_id: str = Form(...),
    sync_interval_minutes: int = Form(60),
    is_enabled: bool = Form(False),
    _: CurrentUser = Depends(require_internal_admin),
):
    async with control_session() as session:
        # Blank bind_password on the form means "leave the saved one
        # alone" -- the form never round-trips the real secret back into
        # the page (see the template), so an empty submit isn't "clear it".
        existing = await get_raw_config(session)
        await save_ldap_config(
            session,
            is_enabled=is_enabled,
            server_uri=server_uri.strip(),
            use_starttls=use_starttls,
            bind_dn=bind_dn.strip(),
            bind_password=bind_password.strip() or existing.get("bind_password", ""),
            user_base_dn=user_base_dn.strip(),
            user_filter=user_filter.strip(),
            user_email_attr=user_email_attr.strip(),
            user_name_attr=user_name_attr.strip(),
            group_base_dn=group_base_dn.strip(),
            group_filter=group_filter.strip(),
            group_name_attr=group_name_attr.strip(),
            group_member_attr=group_member_attr.strip(),
            target_tenant_id=int(target_tenant_id),
            sync_interval_minutes=max(5, sync_interval_minutes),
        )
    return RedirectResponse("/admin/auth-providers/ldap?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth-providers/ldap/test")
async def ldap_config_test(_: CurrentUser = Depends(require_internal_admin)):
    async with control_session() as session:
        config = await get_raw_config(session)
    try:
        await asyncio.to_thread(
            ldap_client.test_bind,
            config["server_uri"],
            config["bind_dn"],
            config["bind_password"],
            config["use_starttls"],
        )
        msg = "ok:Connection and bind succeeded."
    except Exception as exc:
        msg = f"error:{exc}"
    return RedirectResponse(f"/admin/auth-providers/ldap?test_result={quote(msg)}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth-providers/ldap/sync")
async def ldap_config_sync_now(_: CurrentUser = Depends(require_internal_admin)):
    await run_ldap_sync()
    return RedirectResponse("/admin/auth-providers/ldap?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth-providers/saml", response_class=HTMLResponse)
async def saml_config_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        row = await saml_config.get_provider_row(session)
        config = await saml_config.get_raw_config(session)
        tenants = list(
            (await session.execute(select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.name))).scalars()
        )
    return templates.TemplateResponse(
        request,
        "admin/auth_provider_saml.html",
        {
            **nav,
            "ctx": ctx,
            "config": config,
            "tenants": tenants,
            "is_enabled": row.is_enabled if row else False,
            "metadata_url": f"{request.url.scheme}://{request.url.netloc}/auth/saml/metadata",
            "acs_url": f"{request.url.scheme}://{request.url.netloc}/auth/saml/acs",
        },
    )


@router.post("/auth-providers/saml")
async def saml_config_save(
    idp_entity_id: str = Form(...),
    idp_sso_url: str = Form(...),
    idp_x509_cert: str = Form(...),
    sp_entity_id: str = Form(...),
    attr_username: str = Form(""),
    attr_email: str = Form(...),
    attr_first_name: str = Form(...),
    attr_last_name: str = Form(...),
    attr_role: str = Form(...),
    role_admin_value: str = Form(...),
    target_tenant_id: str = Form(...),
    is_enabled: bool = Form(False),
    _: CurrentUser = Depends(require_internal_admin),
):
    async with control_session() as session:
        await saml_config.save_saml_config(
            session,
            is_enabled=is_enabled,
            idp_entity_id=idp_entity_id.strip(),
            idp_sso_url=idp_sso_url.strip(),
            # Accept a cert pasted with or without the PEM header/footer --
            # OneLogin_Saml2_Settings wants just the base64 body.
            idp_x509_cert="".join(
                line.strip()
                for line in idp_x509_cert.splitlines()
                if line.strip() and "BEGIN CERTIFICATE" not in line and "END CERTIFICATE" not in line
            ),
            sp_entity_id=sp_entity_id.strip(),
            attr_username=attr_username.strip(),
            attr_email=attr_email.strip(),
            attr_first_name=attr_first_name.strip(),
            attr_last_name=attr_last_name.strip(),
            attr_role=attr_role.strip(),
            role_admin_value=role_admin_value.strip(),
            target_tenant_id=int(target_tenant_id),
        )
    return RedirectResponse("/admin/auth-providers/saml?ok=1", status_code=status.HTTP_303_SEE_OTHER)


# --------------------------------------------------------- ticket statuses
# The one screen in this module that isn't control-schema: ticket_statuses
# lives per-tenant, but is configured here (internal_admin only, against
# whichever tenant is currently active) rather than under Tickets, at the
# same tier as Branding/Users/SMTP/Syslog Listener.


@router.get("/ticket-statuses", response_class=HTMLResponse)
async def ticket_statuses_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(TicketStatus).order_by(TicketStatus.sort_order, TicketStatus.label)
    status_page = await paginate(tenant_db, stmt, page=page)
    return templates.TemplateResponse(
        request, "admin/ticket_statuses.html", {**nav, "ctx": ctx, "page": status_page}
    )


@router.post("/ticket-statuses")
async def ticket_statuses_create(
    key: str = Form(...),
    label: str = Form(...),
    color: str = Form("#6b7280"),
    is_closed: bool = Form(False),
    sort_order: int = Form(0),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    tenant_db.add(
        TicketStatus(
            key=key.strip().lower().replace(" ", "_"),
            label=label.strip(),
            color=color.strip() or "#6b7280",
            is_closed=is_closed,
            sort_order=sort_order,
        )
    )
    await tenant_db.commit()
    return RedirectResponse("/admin/ticket-statuses", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ticket-statuses/{status_id:int}/delete")
async def ticket_statuses_delete(
    status_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    row = await tenant_db.get(TicketStatus, status_id)
    if row is not None:
        await tenant_db.delete(row)
        await tenant_db.commit()
    return RedirectResponse("/admin/ticket-statuses", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ticket-statuses/{status_id:int}/toggle")
async def ticket_statuses_toggle(
    status_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    row = await tenant_db.get(TicketStatus, status_id)
    if row is not None:
        row.is_active = not row.is_active
        await tenant_db.commit()
    return RedirectResponse("/admin/ticket-statuses", status_code=status.HTTP_303_SEE_OTHER)


# ------------------------------------------------------ notif. channels --
# Also per-tenant (not control-schema) like ticket-statuses above. Just the
# Slack/email destinations -- *when* they fire is entirely decided by
# Tickets > Platform Event rules, not by anything configured here.


def _channel_config_from_form(channel_type: str, form) -> dict:
    if channel_type == "email":
        recipients = [addr.strip() for addr in str(form.get("recipients", "")).split(",") if addr.strip()]
        return {"recipients": recipients}
    if channel_type == "webhook":
        webhook_id = str(form.get("webhook_config_id", "")).strip()
        return {"webhook_id": int(webhook_id)} if webhook_id else {}
    return {"webhook_url": str(form.get("webhook_url", "")).strip()}


@router.get("/notification-channels", response_class=HTMLResponse)
async def notification_channels_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(NotificationChannel).order_by(NotificationChannel.name)
    channel_page = await paginate(tenant_db, stmt, page=page)
    # Decrypted once here (not per-row in the template) so the Edit modal
    # can prefill recipients/webhook_url/webhook_config_id --
    # config_encrypted is otherwise opaque to Jinja.
    channel_configs = {c.id: decrypt_json(c.config_encrypted) for c in channel_page.items}
    webhooks = await webhook_service.list_webhooks(tenant_db)
    return templates.TemplateResponse(
        request,
        "admin/notification_channels.html",
        {
            **nav,
            "ctx": ctx,
            "page": channel_page,
            "channel_types": CHANNEL_TYPES,
            "channel_configs": channel_configs,
            "webhooks": webhooks,
            "default_message_template": notifications.DEFAULT_MESSAGE_TEMPLATE,
            "default_email_message_template": notifications.DEFAULT_EMAIL_MESSAGE_TEMPLATE,
            "default_subject_template": notifications.DEFAULT_SUBJECT_TEMPLATE,
        },
    )


@router.post("/notification-channels")
async def notification_channels_create(
    request: Request,
    channel_type: str = Form(...),
    name: str = Form(...),
    message_template: str = Form(""),
    subject_template: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    form = await request.form()
    config = _channel_config_from_form(channel_type, form)
    tenant_db.add(
        NotificationChannel(
            channel_type=channel_type,
            name=name.strip(),
            config_encrypted=encrypt_json(config),
            message_template=message_template.strip(),
            subject_template=subject_template.strip() or None,
        )
    )
    await tenant_db.commit()
    return RedirectResponse("/admin/notification-channels", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notification-channels/{channel_id:int}/edit")
async def notification_channels_edit(
    request: Request,
    channel_id: int,
    channel_type: str = Form(...),
    name: str = Form(...),
    message_template: str = Form(""),
    subject_template: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    channel = await tenant_db.get(NotificationChannel, channel_id)
    if channel is not None:
        form = await request.form()
        channel.channel_type = channel_type
        channel.name = name.strip()
        channel.config_encrypted = encrypt_json(_channel_config_from_form(channel_type, form))
        channel.message_template = message_template.strip()
        channel.subject_template = subject_template.strip() or None
        await tenant_db.commit()
    return RedirectResponse("/admin/notification-channels", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notification-channels/{channel_id:int}/delete")
async def notification_channels_delete(
    channel_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    channel = await tenant_db.get(NotificationChannel, channel_id)
    if channel is not None:
        await tenant_db.delete(channel)
        await tenant_db.commit()
    return RedirectResponse("/admin/notification-channels", status_code=status.HTTP_303_SEE_OTHER)


# ------------------------------------------------------------- groups ----
# Per-tenant, like ticket-statuses/notification-channels above. The
# assignment target for an approval flow step -- see approval-flows below.


@router.get("/groups", response_class=HTMLResponse)
async def groups_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(Group).order_by(Group.name)
    group_page = await paginate(tenant_db, stmt, page=page)
    member_counts: dict[int, int] = {}
    if group_page.items:
        result = await tenant_db.execute(
            select(GroupMembership.group_id, func.count(GroupMembership.id))
            .where(GroupMembership.group_id.in_([g.id for g in group_page.items]))
            .group_by(GroupMembership.group_id)
        )
        member_counts = dict(result.all())
    return templates.TemplateResponse(
        request,
        "admin/groups.html",
        {**nav, "ctx": ctx, "page": group_page, "member_counts": member_counts},
    )


@router.post("/groups")
async def groups_create(
    name: str = Form(...),
    description: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    tenant_db.add(Group(name=name.strip(), description=description.strip() or None))
    await tenant_db.commit()
    return RedirectResponse("/admin/groups", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/groups/{group_id:int}/delete")
async def groups_delete(
    group_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    row = await tenant_db.get(Group, group_id)
    if row is not None:
        await tenant_db.delete(row)
        await tenant_db.commit()
    return RedirectResponse("/admin/groups", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/groups/{group_id:int}", response_class=HTMLResponse)
async def group_detail(
    request: Request,
    group_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    group = await tenant_db.get(Group, group_id, options=[selectinload(Group.members)])
    if group is None:
        return RedirectResponse("/admin/groups", status_code=status.HTTP_303_SEE_OTHER)
    member_names = await resolve_user_names({m.user_id for m in group.members})
    return templates.TemplateResponse(
        request,
        "admin/group_detail.html",
        {**nav, "ctx": ctx, "group": group, "member_names": member_names},
    )


@router.post("/groups/{group_id:int}/members")
async def group_add_member(
    group_id: int,
    user_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    # Same reasoning as tickets.router.assign_ticket: the picker this form
    # field is filled from only ever offers this tenant's own users, but
    # a crafted POST could name any user id at all -- re-checked here
    # server-side rather than trusted from the form.
    if user_id and await is_assignable_user(int(user_id), ctx.active_tenant.id):
        existing = await tenant_db.execute(
            select(GroupMembership).where(
                GroupMembership.group_id == group_id, GroupMembership.user_id == int(user_id)
            )
        )
        if existing.scalar_one_or_none() is None:
            tenant_db.add(GroupMembership(group_id=group_id, user_id=int(user_id)))
            await tenant_db.commit()
    return RedirectResponse(f"/admin/groups/{group_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/groups/{group_id:int}/members/{membership_id:int}/remove")
async def group_remove_member(
    group_id: int,
    membership_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    row = await tenant_db.get(GroupMembership, membership_id)
    if row is not None and row.group_id == group_id:
        await tenant_db.delete(row)
        await tenant_db.commit()
    return RedirectResponse(f"/admin/groups/{group_id}", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------- approval flows -----
# Per-tenant. A named, ordered sequence of steps, each assigned to a group
# (any one member's approval clears it) or an individual user -- Change
# tickets attach one instance of a flow (ChangeApproval) at creation time.
# The form pre-renders _MAX_APPROVAL_STEPS rows (app.js's [data-step-rows]
# handler show/hides them -- no JS framework here, so no dynamic DOM
# templating); a row with neither a group nor a user picked is simply
# skipped on submit, so a flow can have 1-10 steps regardless of which
# rows the add/remove buttons left visible.
_MAX_APPROVAL_STEPS = 10


@router.get("/approval-flows", response_class=HTMLResponse)
async def approval_flows_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(ApprovalFlow).options(selectinload(ApprovalFlow.steps)).order_by(ApprovalFlow.name)
    flow_page = await paginate(tenant_db, stmt, page=page)
    groups_result = await tenant_db.execute(select(Group).order_by(Group.name))
    group_names = {g.id: g.name for g in groups_result.scalars()}
    user_ids = {s.approver_user_id for f in flow_page.items for s in f.steps if s.approver_user_id}
    step_user_names = await resolve_user_names(user_ids)
    return templates.TemplateResponse(
        request,
        "admin/approval_flows.html",
        {
            **nav,
            "ctx": ctx,
            "page": flow_page,
            "group_names": group_names,
            "step_user_names": step_user_names,
        },
    )


@router.get("/approval-flows/new", response_class=HTMLResponse)
async def approval_flows_new_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    groups_result = await tenant_db.execute(select(Group).order_by(Group.name))
    groups = list(groups_result.scalars())
    return templates.TemplateResponse(
        request,
        "admin/approval_flow_form.html",
        {
            **nav,
            "ctx": ctx,
            "flow": None,
            "groups": groups,
            "step_range": range(1, _MAX_APPROVAL_STEPS + 1),
            "step_prefill": {},
        },
    )


@router.post("/approval-flows")
async def approval_flows_create(
    request: Request,
    name: str = Form(...),
    is_default: bool = Form(False),
    notify_syslog_on_approval: bool = Form(False),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    form = await request.form()
    if is_default:
        await tenant_db.execute(ApprovalFlow.__table__.update().values(is_default=False))
    flow = ApprovalFlow(name=name.strip(), is_default=is_default, notify_syslog_on_approval=notify_syslog_on_approval)
    tenant_db.add(flow)
    await tenant_db.flush()
    await _replace_approval_steps(tenant_db, flow.id, form, tenant_id=ctx.active_tenant.id)
    await tenant_db.commit()
    return RedirectResponse("/admin/approval-flows", status_code=status.HTTP_303_SEE_OTHER)


async def _replace_approval_steps(tenant_db: AsyncSession, flow_id: int, form, *, tenant_id: int) -> None:
    """Shared by create and edit -- steps have no identity worth preserving
    across an edit (they're just an ordered label/approver list), so an
    edit rebuilds them from the submitted form rather than diffing against
    what's already there."""
    sort_order = 0
    for i in range(1, _MAX_APPROVAL_STEPS + 1):
        group_id = str(form.get(f"step_group_{i}", "")).strip()
        user_id = str(form.get(f"step_user_{i}", "")).strip()
        if not group_id and not user_id:
            continue
        # Same reasoning as assign_ticket/group_add_member -- a step's
        # approver_user_id is a plain form field, re-validated here rather
        # than trusted, so it can't name a user outside this tenant.
        if user_id and not group_id and not await is_assignable_user(int(user_id), tenant_id):
            continue
        label = str(form.get(f"step_label_{i}", "")).strip() or f"Step {sort_order + 1}"
        tenant_db.add(
            ApprovalFlowStep(
                flow_id=flow_id,
                sort_order=sort_order,
                label=label,
                approver_group_id=int(group_id) if group_id else None,
                approver_user_id=int(user_id) if not group_id and user_id else None,
            )
        )
        sort_order += 1


@router.get("/approval-flows/{flow_id:int}/edit", response_class=HTMLResponse)
async def approval_flows_edit_form(
    request: Request,
    flow_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    flow = await tenant_db.get(ApprovalFlow, flow_id, options=[selectinload(ApprovalFlow.steps)])
    if flow is None:
        return RedirectResponse("/admin/approval-flows", status_code=status.HTTP_303_SEE_OTHER)
    groups_result = await tenant_db.execute(select(Group).order_by(Group.name))
    groups = list(groups_result.scalars())
    user_names = await resolve_user_names({s.approver_user_id for s in flow.steps if s.approver_user_id})
    # Steps have no fixed slot -- keyed here by their position (1-based) in
    # sort_order so the form's step_range loop can prefill row i from
    # step_prefill.get(i) the same way it reads step_range itself.
    step_prefill = {
        i + 1: {
            "label": s.label,
            "group_id": s.approver_group_id,
            "user_id": s.approver_user_id,
            "user_label": user_names.get(s.approver_user_id, "") if s.approver_user_id else "",
        }
        for i, s in enumerate(sorted(flow.steps, key=lambda s: s.sort_order))
    }
    return templates.TemplateResponse(
        request,
        "admin/approval_flow_form.html",
        {
            **nav,
            "ctx": ctx,
            "flow": flow,
            "groups": groups,
            "step_range": range(1, _MAX_APPROVAL_STEPS + 1),
            "step_prefill": step_prefill,
        },
    )


@router.post("/approval-flows/{flow_id:int}/edit")
async def approval_flows_edit(
    request: Request,
    flow_id: int,
    name: str = Form(...),
    is_default: bool = Form(False),
    notify_syslog_on_approval: bool = Form(False),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    flow = await tenant_db.get(ApprovalFlow, flow_id, options=[selectinload(ApprovalFlow.steps)])
    if flow is None:
        return RedirectResponse("/admin/approval-flows", status_code=status.HTTP_303_SEE_OTHER)
    form = await request.form()
    if is_default:
        await tenant_db.execute(ApprovalFlow.__table__.update().values(is_default=False))
    flow.name = name.strip()
    flow.is_default = is_default
    flow.notify_syslog_on_approval = notify_syslog_on_approval
    for step in list(flow.steps):
        await tenant_db.delete(step)
    await tenant_db.flush()
    await _replace_approval_steps(tenant_db, flow.id, form, tenant_id=ctx.active_tenant.id)
    await tenant_db.commit()
    return RedirectResponse("/admin/approval-flows", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/approval-flows/{flow_id:int}/delete")
async def approval_flows_delete(
    flow_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    row = await tenant_db.get(ApprovalFlow, flow_id)
    if row is not None:
        await tenant_db.delete(row)
        await tenant_db.commit()
    return RedirectResponse("/admin/approval-flows", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/approval-flows/{flow_id:int}/set-default")
async def approval_flows_set_default(
    flow_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    await tenant_db.execute(ApprovalFlow.__table__.update().values(is_default=False))
    row = await tenant_db.get(ApprovalFlow, flow_id)
    if row is not None:
        row.is_default = True
        await tenant_db.commit()
    return RedirectResponse("/admin/approval-flows", status_code=status.HTTP_303_SEE_OTHER)


# ----------------------------------------------------- service catalog ---
# Per-tenant. Each item is an up-to-MAX_CATALOG_FIELDS-question form
# (rain.modules.catalog.schemas) that produces a ticket on submission --
# see rain.modules.catalog.service for the shared create/submit logic both
# /catalog (main app, Records Authority) and the customer portal's Catalog
# tab call, so a submission behaves identically either way. The form
# pre-renders MAX_CATALOG_FIELDS rows, reusing the exact same [data-step-
# field] JS show/hide Approval Flows' step builder uses above -- a row
# with no field_key is simply skipped on submit (see catalog_service.
# replace_catalog_fields), so an item can have 0-10 questions regardless
# of which rows the add/remove buttons left visible.


def _catalog_item_form_error(ticket_type: str, requires_approval: bool, approval_flow_id: str) -> str | None:
    if ticket_type == "change" and not (requires_approval and approval_flow_id):
        return "Change requests must require approval, with a flow selected."
    return None


async def _catalog_form_context(tenant_db: AsyncSession, ctx: RequestContext, *, item: ServiceCatalogItem | None) -> dict:
    nav = await build_nav_context(ctx)
    flows_result = await tenant_db.execute(select(ApprovalFlow).order_by(ApprovalFlow.name))
    field_prefill = {i + 1: f for i, f in enumerate(sorted(item.fields, key=lambda f: f.sort_order))} if item else {}
    return {
        **nav,
        "ctx": ctx,
        "item": item,
        "flows": list(flows_result.scalars()),
        "ticket_types": TICKET_TYPES,
        "payload_formats": PAYLOAD_FORMATS,
        "source_modes": SOURCE_MODES,
        "severities": SEVERITIES,
        "field_range": range(1, MAX_CATALOG_FIELDS + 1),
        "field_prefill": field_prefill,
    }


@router.get("/catalog", response_class=HTMLResponse)
async def catalog_items_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    items = await catalog_service.list_catalog_items(tenant_db)
    return templates.TemplateResponse(request, "admin/catalog_items.html", {**nav, "ctx": ctx, "items": items})


@router.get("/catalog/new", response_class=HTMLResponse)
async def catalog_item_new_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    context = await _catalog_form_context(tenant_db, ctx, item=None)
    return templates.TemplateResponse(request, "admin/catalog_item_form.html", context)


@router.post("/catalog")
async def catalog_item_create(
    request: Request,
    name: str = Form(...),
    key: str = Form(...),
    description: str = Form(""),
    ticket_type: str = Form("incident"),
    default_severity: str = Form("medium"),
    payload_format: str = Form("json"),
    requires_approval: bool = Form(False),
    approval_flow_id: str = Form(""),
    is_active: bool = Form(False),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    # An incident/vulnerability has no approval concept -- normalized here
    # rather than trusting the client, which only ever hides (not
    # disables) the requires_approval/approval_flow_id controls for a
    # non-"change" Produces via CSS -- HTML's hidden attribute doesn't
    # stop a field from still being submitted, so a stale checked box
    # left over from switching Produces away from "change" (or a request
    # built by hand) would otherwise still save.
    if ticket_type != "change":
        requires_approval = False
        approval_flow_id = ""

    error = _catalog_item_form_error(ticket_type, requires_approval, approval_flow_id)
    if error:
        return RedirectResponse(f"/admin/catalog/new?error={quote(error)}", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    item = ServiceCatalogItem(
        name=name.strip(),
        key=key.strip().lower(),
        description=description.strip() or None,
        ticket_type=ticket_type,
        default_severity=default_severity,
        payload_format=payload_format,
        requires_approval=requires_approval,
        approval_flow_id=int(approval_flow_id) if requires_approval and approval_flow_id else None,
        is_active=is_active,
        created_by=ctx.user.id,
        updated_by=ctx.user.id,
    )
    # add() before replace_catalog_fields, not flush() -- item is only
    # "pending" at that point (in the session, not yet a real row), and
    # its never-touched .fields collection stays safe to read/populate
    # purely in-memory either way. A *flush* first would make it
    # persistent-but-unloaded instead, and replace_catalog_fields reading
    # that collection would then need to lazy-load it from the DB, which
    # fails synchronously under asyncpg's async driver (MissingGreenlet,
    # confirmed live) -- see that function's own docstring.
    tenant_db.add(item)
    await catalog_service.replace_catalog_fields(tenant_db, item, form, max_fields=MAX_CATALOG_FIELDS)
    await tenant_db.commit()
    return RedirectResponse("/admin/catalog", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/catalog/{item_id:int}/edit", response_class=HTMLResponse)
async def catalog_item_edit_form(
    request: Request,
    item_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    item = await catalog_service.get_catalog_item(tenant_db, item_id)
    if item is None:
        return RedirectResponse("/admin/catalog", status_code=status.HTTP_303_SEE_OTHER)
    context = await _catalog_form_context(tenant_db, ctx, item=item)
    return templates.TemplateResponse(request, "admin/catalog_item_form.html", context)


@router.post("/catalog/{item_id:int}/edit")
async def catalog_item_edit(
    request: Request,
    item_id: int,
    name: str = Form(...),
    key: str = Form(...),
    description: str = Form(""),
    ticket_type: str = Form("incident"),
    default_severity: str = Form("medium"),
    payload_format: str = Form("json"),
    requires_approval: bool = Form(False),
    approval_flow_id: str = Form(""),
    is_active: bool = Form(False),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    item = await catalog_service.get_catalog_item(tenant_db, item_id)
    if item is None:
        return RedirectResponse("/admin/catalog", status_code=status.HTTP_303_SEE_OTHER)

    # See catalog_item_create's identical normalization for why this
    # can't just rely on the form hiding these controls client-side.
    if ticket_type != "change":
        requires_approval = False
        approval_flow_id = ""

    error = _catalog_item_form_error(ticket_type, requires_approval, approval_flow_id)
    if error:
        return RedirectResponse(f"/admin/catalog/{item_id}/edit?error={quote(error)}", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    item.name = name.strip()
    item.key = key.strip().lower()
    item.description = description.strip() or None
    item.ticket_type = ticket_type
    item.default_severity = default_severity
    item.payload_format = payload_format
    item.requires_approval = requires_approval
    item.approval_flow_id = int(approval_flow_id) if requires_approval and approval_flow_id else None
    item.is_active = is_active
    item.updated_by = ctx.user.id
    await catalog_service.replace_catalog_fields(tenant_db, item, form, max_fields=MAX_CATALOG_FIELDS)
    await tenant_db.commit()
    return RedirectResponse("/admin/catalog", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/catalog/{item_id:int}/delete")
async def catalog_item_delete(
    item_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    item = await tenant_db.get(ServiceCatalogItem, item_id)
    if item is not None:
        await catalog_service.delete_catalog_item(tenant_db, item)
    return RedirectResponse("/admin/catalog", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/catalog/{item_id:int}/toggle")
async def catalog_item_toggle(
    item_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    item = await tenant_db.get(ServiceCatalogItem, item_id)
    if item is not None:
        await catalog_service.set_active(tenant_db, item, not item.is_active)
    return RedirectResponse("/admin/catalog", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/catalog/fields/preview", response_class=HTMLResponse)
async def catalog_field_preview(
    request: Request,
    source_document_id: str = Form(""),
    source_mode: str = Form(""),
    source_expression: str = Form(""),
    field_type: str = Form("text"),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    """Backs the "Preview" button on each field row while designing a
    catalog item's form -- resolves against the live document with
    nothing saved yet, same as how /assets/fields-for-type/{id} previews
    against live data mid-form. Requires only require_admin (not a
    specific item), since a field row being previewed might not belong to
    a saved item at all yet (a brand-new "New service" form)."""
    resolved = await catalog_service.resolve_field_source(
        tenant_db,
        document_id=int(source_document_id) if source_document_id else None,
        mode=source_mode or None,
        expression=source_expression or None,
        is_select=(field_type == "select"),
    )
    return templates.TemplateResponse(
        request, "admin/_catalog_field_preview.html", {"resolved": resolved, "is_select": field_type == "select"}
    )


# ------------------------------------------------------------ webhooks ---


@router.get("/webhooks", response_class=HTMLResponse)
async def webhooks_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(WebhookConfig).order_by(WebhookConfig.name)
    webhook_page = await paginate(tenant_db, stmt, page=page)
    return templates.TemplateResponse(
        request, "admin/webhooks.html", {**nav, "ctx": ctx, "page": webhook_page}
    )


@router.get("/webhooks/new", response_class=HTMLResponse)
async def webhooks_new_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "admin/webhook_form.html", {**nav, "ctx": ctx, "webhook": None})


@router.post("/webhooks")
async def webhooks_create(
    name: str = Form(...),
    url: str = Form(...),
    http_method: str = Form("POST"),
    headers_text: str = Form(""),
    payload_template: str = Form("{}"),
    timeout_seconds: int = Form(10),
    success_codes: str = Form("200,201,202,204"),
    alert_on_failure: bool = Form(False),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    # Fail fast with a clear reason at save time -- the same check
    # call_webhook() re-applies on every actual call (the real
    # enforcement point, since a URL that resolves safely today could
    # resolve to something internal later), so this is UX, not the
    # security boundary itself.
    unsafe_reason = await check_outbound_url(url.strip())
    if unsafe_reason is not None:
        return RedirectResponse(
            f"/admin/webhooks/new?error={quote(f'URL rejected: {unsafe_reason}')}", status_code=status.HTTP_303_SEE_OTHER
        )
    await webhook_service.create_webhook(
        tenant_db,
        name=name.strip(),
        url=url.strip(),
        http_method=http_method,
        headers=webhook_service.parse_headers_text(headers_text),
        payload_template=payload_template or "{}",
        timeout_seconds=max(1, timeout_seconds),
        success_codes=success_codes.strip() or "200,201,202,204",
        alert_on_failure=alert_on_failure,
        created_by=ctx.user.id,
    )
    return RedirectResponse("/admin/webhooks", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/webhooks/{webhook_id:int}/edit", response_class=HTMLResponse)
async def webhooks_edit_form(
    request: Request,
    webhook_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    webhook = await webhook_service.get_webhook(tenant_db, webhook_id)
    if webhook is None:
        return RedirectResponse("/admin/webhooks", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "admin/webhook_form.html",
        {**nav, "ctx": ctx, "webhook": webhook, "headers_text": webhook_service.format_headers_text(webhook.headers)},
    )


@router.post("/webhooks/{webhook_id:int}/edit")
async def webhooks_edit(
    webhook_id: int,
    name: str = Form(...),
    url: str = Form(...),
    http_method: str = Form("POST"),
    headers_text: str = Form(""),
    payload_template: str = Form("{}"),
    timeout_seconds: int = Form(10),
    success_codes: str = Form("200,201,202,204"),
    alert_on_failure: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    unsafe_reason = await check_outbound_url(url.strip())
    if unsafe_reason is not None:
        return RedirectResponse(
            f"/admin/webhooks/{webhook_id}/edit?error={quote(f'URL rejected: {unsafe_reason}')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    webhook = await webhook_service.get_webhook(tenant_db, webhook_id)
    if webhook is not None:
        await webhook_service.update_webhook(
            tenant_db,
            webhook,
            name=name.strip(),
            url=url.strip(),
            http_method=http_method,
            headers=webhook_service.parse_headers_text(headers_text),
            payload_template=payload_template or "{}",
            timeout_seconds=max(1, timeout_seconds),
            success_codes=success_codes.strip() or "200,201,202,204",
            alert_on_failure=alert_on_failure,
        )
    return RedirectResponse("/admin/webhooks", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/webhooks/{webhook_id:int}/delete")
async def webhooks_delete(
    webhook_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    webhook = await webhook_service.get_webhook(tenant_db, webhook_id)
    if webhook is not None:
        await webhook_service.delete_webhook(tenant_db, webhook)
    return RedirectResponse("/admin/webhooks", status_code=status.HTTP_303_SEE_OTHER)
