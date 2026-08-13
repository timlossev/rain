"""Platform-level administration: branding, tenants, users/roles, and a
read-only view of auth provider placeholders. internal_admin only, except
the tenant-switch action which any internal_admin uses to pick their
active tenant (client users are pinned to one and never see this)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.core.config_store import FONT_CHOICES, config_store
from rain.core.crypto import encrypt_json
from rain.core.pagination import paginate
from rain.core.rbac import require_internal_admin, require_login
from rain.core.security import hash_password
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.db.base import control_session
from rain.db.control_models import AuthProviderConfig, Session as SessionRow, SyslogSourceMap, Tenant, User
from rain.db.provisioning import InvalidSlugError, provision_tenant
from rain.db.tenant_models import ApprovalFlow, ApprovalFlowStep, Group, GroupMembership, NotificationChannel, TicketStatus
from rain.modules.tickets.schemas import CHANNEL_TYPES
from rain.settings import get_settings
from rain.web.nav import build_nav_context
from rain.web.templating import templates
from rain.web.uploads import UploadError, save_logo_upload

router = APIRouter(prefix="/admin")


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request, ctx: RequestContext = Depends(get_request_context), _: CurrentUser = Depends(require_login)
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "admin/dashboard.html", {**nav, "ctx": ctx})


@router.get("/branding", response_class=HTMLResponse)
async def branding_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(
        request, "admin/branding.html", {**nav, "ctx": ctx, "error": None, "font_choices": FONT_CHOICES}
    )


@router.post("/branding")
async def branding_submit(
    request: Request,
    instance_name: str = Form(...),
    accent_color: str = Form(...),
    font_family: str = Form(""),
    logo: UploadFile | None = None,
    ctx: RequestContext = Depends(get_request_context),
    user: CurrentUser = Depends(require_internal_admin),
):
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
            nav = await build_nav_context(ctx)
            return templates.TemplateResponse(
                request, "admin/branding.html", {**nav, "ctx": ctx, "error": str(exc)}, status_code=400
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
            result = await session.execute(select(Tenant).order_by(Tenant.name))
            tenants = list(result.scalars())
        return templates.TemplateResponse(
            request,
            "admin/tenants.html",
            {**nav, "ctx": ctx, "tenants": tenants, "error": str(exc)},
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
    if role_key == "client" and not tenant_id:
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
    if role_key == "client" and not tenant_id:
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


@router.get("/syslog-sources", response_class=HTMLResponse)
async def syslog_sources_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        stmt = (
            select(SyslogSourceMap)
            .options(selectinload(SyslogSourceMap.tenant))
            .order_by(SyslogSourceMap.sort_order)
        )
        source_page = await paginate(session, stmt, page=page)
        tenants = list((await session.execute(select(Tenant).order_by(Tenant.name))).scalars())
    return templates.TemplateResponse(
        request,
        "admin/syslog_sources.html",
        {**nav, "ctx": ctx, "page": source_page, "tenants": tenants, "listener_port": get_settings().syslog_port},
    )


@router.post("/syslog-sources")
async def syslog_sources_create(
    tenant_id: int = Form(...),
    match_field: str = Form(...),
    pattern: str = Form(...),
    is_regex: bool = Form(False),
    sort_order: int = Form(0),
    _: CurrentUser = Depends(require_internal_admin),
):
    async with control_session() as session:
        session.add(
            SyslogSourceMap(
                tenant_id=tenant_id,
                match_field=match_field,
                pattern=pattern.strip(),
                is_regex=is_regex,
                sort_order=sort_order,
            )
        )
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


# --------------------------------------------------------- ticket statuses
# The one screen in this module that isn't control-schema: ticket_statuses
# lives per-tenant, but is configured here (internal_admin only, against
# whichever tenant is currently active) rather than under Tickets, at the
# same tier as Branding/Users/SMTP/Syslog Sources.


@router.get("/ticket-statuses", response_class=HTMLResponse)
async def ticket_statuses_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_internal_admin),
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
    _: CurrentUser = Depends(require_internal_admin),
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
    status_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_internal_admin)
):
    row = await tenant_db.get(TicketStatus, status_id)
    if row is not None:
        await tenant_db.delete(row)
        await tenant_db.commit()
    return RedirectResponse("/admin/ticket-statuses", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ticket-statuses/{status_id:int}/toggle")
async def ticket_statuses_toggle(
    status_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_internal_admin)
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


@router.get("/notification-channels", response_class=HTMLResponse)
async def notification_channels_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(NotificationChannel).order_by(NotificationChannel.name)
    channel_page = await paginate(tenant_db, stmt, page=page)
    return templates.TemplateResponse(
        request,
        "admin/notification_channels.html",
        {**nav, "ctx": ctx, "page": channel_page, "channel_types": CHANNEL_TYPES},
    )


@router.post("/notification-channels")
async def notification_channels_create(
    request: Request,
    channel_type: str = Form(...),
    name: str = Form(...),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_internal_admin),
):
    form = await request.form()
    if channel_type == "email":
        recipients = [addr.strip() for addr in str(form.get("recipients", "")).split(",") if addr.strip()]
        config = {"recipients": recipients}
    else:
        config = {"webhook_url": str(form.get("webhook_url", "")).strip()}

    tenant_db.add(
        NotificationChannel(channel_type=channel_type, name=name.strip(), config_encrypted=encrypt_json(config))
    )
    await tenant_db.commit()
    return RedirectResponse("/admin/notification-channels", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notification-channels/{channel_id:int}/delete")
async def notification_channels_delete(
    channel_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_internal_admin)
):
    channel = await tenant_db.get(NotificationChannel, channel_id)
    if channel is not None:
        await tenant_db.delete(channel)
        await tenant_db.commit()
    return RedirectResponse("/admin/notification-channels", status_code=status.HTTP_303_SEE_OTHER)


# ------------------------------------------------------------- groups ----
# Per-tenant, like ticket-statuses/notification-channels above. The
# assignment target for an approval flow step -- see approval-flows below.


async def _group_member_names(user_ids: set[int]) -> dict[int, str]:
    """Same batched cross-schema lookup as rain.modules.tickets.router's
    _user_names -- kept as its own copy rather than importing a "_"-prefixed
    name across modules."""
    if not user_ids:
        return {}
    async with control_session() as session:
        result = await session.execute(select(User).where(User.id.in_(user_ids)))
        return {u.id: u.display_name for u in result.scalars()}


@router.get("/groups", response_class=HTMLResponse)
async def groups_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_internal_admin),
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
    _: CurrentUser = Depends(require_internal_admin),
):
    tenant_db.add(Group(name=name.strip(), description=description.strip() or None))
    await tenant_db.commit()
    return RedirectResponse("/admin/groups", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/groups/{group_id:int}/delete")
async def groups_delete(
    group_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_internal_admin)
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
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    group = await tenant_db.get(Group, group_id, options=[selectinload(Group.members)])
    if group is None:
        return RedirectResponse("/admin/groups", status_code=status.HTTP_303_SEE_OTHER)
    member_names = await _group_member_names({m.user_id for m in group.members})
    return templates.TemplateResponse(
        request,
        "admin/group_detail.html",
        {**nav, "ctx": ctx, "group": group, "member_names": member_names},
    )


@router.post("/groups/{group_id:int}/members")
async def group_add_member(
    group_id: int,
    user_id: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_internal_admin),
):
    if user_id:
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
    _: CurrentUser = Depends(require_internal_admin),
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
# The create form offers a fixed 5 step rows rather than a JS-driven
# add/remove-row builder (this app has no JS framework); a row with neither
# a group nor a user picked is simply skipped, so a flow can have 1-5 steps.
_MAX_APPROVAL_STEPS = 5


@router.get("/approval-flows", response_class=HTMLResponse)
async def approval_flows_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(ApprovalFlow).options(selectinload(ApprovalFlow.steps)).order_by(ApprovalFlow.name)
    flow_page = await paginate(tenant_db, stmt, page=page)
    groups_result = await tenant_db.execute(select(Group).order_by(Group.name))
    group_names = {g.id: g.name for g in groups_result.scalars()}
    user_ids = {s.approver_user_id for f in flow_page.items for s in f.steps if s.approver_user_id}
    step_user_names = await _group_member_names(user_ids)
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
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    groups_result = await tenant_db.execute(select(Group).order_by(Group.name))
    groups = list(groups_result.scalars())
    return templates.TemplateResponse(
        request,
        "admin/approval_flow_form.html",
        {**nav, "ctx": ctx, "groups": groups, "step_range": range(1, _MAX_APPROVAL_STEPS + 1)},
    )


@router.post("/approval-flows")
async def approval_flows_create(
    request: Request,
    name: str = Form(...),
    is_default: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_internal_admin),
):
    form = await request.form()
    if is_default:
        await tenant_db.execute(ApprovalFlow.__table__.update().values(is_default=False))
    flow = ApprovalFlow(name=name.strip(), is_default=is_default)
    tenant_db.add(flow)
    await tenant_db.flush()

    sort_order = 0
    for i in range(1, _MAX_APPROVAL_STEPS + 1):
        group_id = str(form.get(f"step_group_{i}", "")).strip()
        user_id = str(form.get(f"step_user_{i}", "")).strip()
        if not group_id and not user_id:
            continue
        label = str(form.get(f"step_label_{i}", "")).strip() or f"Step {sort_order + 1}"
        tenant_db.add(
            ApprovalFlowStep(
                flow_id=flow.id,
                sort_order=sort_order,
                label=label,
                approver_group_id=int(group_id) if group_id else None,
                approver_user_id=int(user_id) if not group_id and user_id else None,
            )
        )
        sort_order += 1
    await tenant_db.commit()
    return RedirectResponse("/admin/approval-flows", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/approval-flows/{flow_id:int}/delete")
async def approval_flows_delete(
    flow_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_internal_admin)
):
    row = await tenant_db.get(ApprovalFlow, flow_id)
    if row is not None:
        await tenant_db.delete(row)
        await tenant_db.commit()
    return RedirectResponse("/admin/approval-flows", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/approval-flows/{flow_id:int}/set-default")
async def approval_flows_set_default(
    flow_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_internal_admin)
):
    await tenant_db.execute(ApprovalFlow.__table__.update().values(is_default=False))
    row = await tenant_db.get(ApprovalFlow, flow_id)
    if row is not None:
        row.is_default = True
        await tenant_db.commit()
    return RedirectResponse("/admin/approval-flows", status_code=status.HTTP_303_SEE_OTHER)
