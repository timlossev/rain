from __future__ import annotations

import io
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.convertors import Convertor, register_url_convertor

from rain.core.export_columns import merge_profile_columns
from rain.core.pagination import paginate
from rain.core.rbac import require_admin, require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.core.tenant_config import get_tenant_config
from rain.core.user_names import resolve_user_names
from rain.db.base import control_session
from rain.db.control_models import User
from rain.db.tenant_models import (
    Asset,
    CorrelationRule,
    Group,
    NotificationChannel,
    PlatformEventAction,
    PlatformEventRule,
    Ticket,
    TicketRule,
    WebhookConfig,
)
from rain.modules.assets import service as asset_service
from rain.modules.documents import service as document_service
from rain.modules.tickets import exporter, platform_events, service
from rain.modules.tickets.correlation import GROUP_BY_FIELDS, RULE_TYPES
from rain.modules.tickets.schemas import MATCH_FIELDS, SEVERITIES, TICKET_TYPES
from rain.modules.webhooks import service as webhook_service
from rain.web.nav import build_nav_context
from rain.web.pdf import render_pdf
from rain.web.safe_redirect import safe_relative_path
from rain.web.templating import templates

class _TicketRefConvertor(Convertor):
    """Matches a ticket_number ("INC-000123"/"VULN-000045"/"CHG-000012" --
    the URL scheme ticket detail links use) or, for back-compat with any
    link/bookmark built before that switch, a bare integer id. A real
    regex-constrained path converter, not a plain {ticket_ref} str -- that
    would match *any* single path segment and shadow every literal route
    below it ("/new", "/rules", "/export/run", ...) regardless of
    registration order; see docs/architecture.md's "A routing bug worth
    knowing about" for the exact failure mode this sidesteps."""

    regex = r"(?:INC|VULN|CHG)-\d+|\d+"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


register_url_convertor("ticket_ref", _TicketRefConvertor())

router = APIRouter(prefix="/tickets", tags=["Tickets"])


# ------------------------------------------------------------- tickets ---


@router.get("", response_class=HTMLResponse)
async def list_tickets(
    request: Request,
    ticket_type: str | None = None,
    ticket_status: str | None = None,
    assigned: str | None = None,  # "me" | "unassigned" | None
    problematic: str | None = None,  # "1" | None
    sort: str | None = None,
    dir: str = "desc",
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    dir = "asc" if dir == "asc" else "desc"
    stmt = service.ticket_list_stmt(
        ticket_type=ticket_type,
        status=ticket_status,
        assigned_to=ctx.user.id if assigned == "me" else None,
        unassigned=assigned == "unassigned",
        problematic_only=bool(problematic),
        sort=sort,
        direction=dir,
    )
    ticket_page = await paginate(tenant_db, stmt, page=page)
    statuses = await service.list_statuses(tenant_db)
    status_colors = {s.key: s.color for s in statuses}
    user_names = await resolve_user_names({t.assignee_user_id for t in ticket_page.items})
    return templates.TemplateResponse(
        request,
        "tickets/list.html",
        {
            **nav,
            "ctx": ctx,
            "page": ticket_page,
            "ticket_types": TICKET_TYPES,
            "statuses": statuses,
            "status_colors": status_colors,
            "selected_type": ticket_type,
            "selected_status": ticket_status,
            "selected_assigned": assigned,
            "selected_problematic": bool(problematic),
            "selected_sort": sort if sort in service.SORTABLE_COLUMNS else "created_at",
            "selected_dir": dir,
            "user_names": user_names,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_ticket_form(
    request: Request,
    ticket_type: str = "incident",
    source_event_id: int | None = None,
    source_ticket_id: int | None = None,
    error: str | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    event = await service.get_event(tenant_db, source_event_id) if source_event_id else None
    source_ticket = await service.get_ticket(tenant_db, source_ticket_id) if source_ticket_id else None

    if source_ticket is not None:
        prefill_title = f"Change for {source_ticket.ticket_number}: {source_ticket.title}"
        prefill_description = source_ticket.description or ""
    else:
        prefill_title = f"{event.program or event.host or 'Event'}: {event.message[:120]}" if event else ""
        prefill_description = event.message if event else ""
    suggested_asset_id = source_ticket.asset_id if source_ticket else None
    suggested_asset_name = source_ticket.asset.name if source_ticket and source_ticket.asset else ""
    if event is not None and event.host and suggested_asset_id is None:
        result = await tenant_db.execute(select(Asset).where(Asset.external_id == event.host).limit(1))
        suggested_asset = result.scalar_one_or_none()
        if suggested_asset is not None:
            suggested_asset_id = suggested_asset.id
            suggested_asset_name = suggested_asset.name

    flows = await service.list_approval_flows(tenant_db)
    default_flow = next((f for f in flows if f.is_default), None)

    return templates.TemplateResponse(
        request,
        "tickets/form.html",
        {
            **nav,
            "ctx": ctx,
            "ticket_types": TICKET_TYPES,
            "severities": SEVERITIES,
            "selected_type": ticket_type,
            "source_event_id": source_event_id,
            "source_ticket_id": source_ticket_id,
            "source_ticket": source_ticket,
            "prefill_title": prefill_title,
            "prefill_description": prefill_description,
            "suggested_asset_id": suggested_asset_id,
            "suggested_asset_name": suggested_asset_name,
            "flows": flows,
            "default_flow_id": default_flow.id if default_flow else None,
            "error": error,
        },
    )


@router.post("")
async def create_ticket(
    ticket_type: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    severity: str = Form("medium"),
    asset_id: str = Form(""),
    source_event_id: str = Form(""),
    source_ticket_id: str = Form(""),
    assignee_user_id: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    approval_flow_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    # Changes must name a real, usable approval flow -- checked before
    # create_ticket() below, not after, so an invalid/missing flow never
    # results in an unprotected change ticket getting filed at all.
    if ticket_type == "change":
        flow_id = int(approval_flow_id) if approval_flow_id else None
        if flow_id is None or not await service.approval_flow_exists(tenant_db, flow_id):
            params = urlencode(
                {"ticket_type": "change", "error": "Changes require an approval flow -- pick one below."}
            )
            return RedirectResponse(f"/tickets/new?{params}", status_code=status.HTTP_303_SEE_OTHER)

    # service.create_ticket() already evaluates Platform Event rules
    # (notify Slack/email/webhook/etc, if any are configured to match) --
    # see rain.modules.tickets.notifications for why there's no separate
    # unconditional notify step here anymore.
    ticket = await service.create_ticket(
        tenant_db,
        ticket_type=ticket_type,
        title=title.strip(),
        description=description.strip() or None,
        severity=severity,
        asset_id=int(asset_id) if asset_id else None,
        source_event_id=int(source_event_id) if source_event_id else None,
        source_ticket_id=int(source_ticket_id) if source_ticket_id else None,
        start_date=datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc) if start_date else None,
        end_date=datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) if end_date else None,
        assignee_user_id=int(assignee_user_id) if assignee_user_id else None,
        reporter_user_id=ctx.user.id,
    )
    if ticket_type == "change":
        await service.start_approval(tenant_db, ticket, int(approval_flow_id) if approval_flow_id else None)
    return RedirectResponse(f"/tickets/{ticket.ticket_number}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users/search")
async def search_assignable_users(
    q: str = "",
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_login),
):
    """Backs the assignee predictive-search field on the ticket form/detail
    page (same interaction shape as Quick Navigation, but this list can't be
    pre-rendered into the page like the nav tree is -- it's a live query
    over every user who could plausibly be assigned: this tenant's client
    users, plus internal admins, who aren't tenant-scoped)."""
    q = q.strip()
    if not ctx.active_tenant or len(q) < 2:
        return []
    async with control_session() as session:
        stmt = (
            select(User)
            .where(
                User.is_active.is_(True),
                (User.tenant_id == ctx.active_tenant.id) | (User.role_key == "internal_admin"),
                (User.display_name.ilike(f"%{q}%")) | (User.email.ilike(f"%{q}%")),
            )
            .order_by(User.display_name)
            .limit(8)
        )
        result = await session.execute(stmt)
        return [{"id": u.id, "label": f"{u.display_name} ({u.email})"} for u in result.scalars()]


@router.post("/{ticket_id:int}/title")
async def rename_ticket(
    ticket_id: int,
    title: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        await service.update_title(tenant_db, ticket, title, changed_by_user_id=ctx.user.id)
    return RedirectResponse(f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id:int}/severity")
async def change_severity(
    ticket_id: int,
    severity: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        await service.update_severity(tenant_db, ticket, severity, changed_by_user_id=ctx.user.id)
    return RedirectResponse(f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id:int}/assign")
async def assign_ticket(
    ticket_id: int,
    assignee_user_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        await service.update_assignee(
            tenant_db,
            ticket,
            int(assignee_user_id) if assignee_user_id else None,
            changed_by_user_id=ctx.user.id,
        )
    return RedirectResponse(f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/assets/search")
async def search_tickets_assets(
    q: str = "",
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Backs the affected-asset predictive-search field on the ticket
    form/detail page -- same shape as search_assignable_users above, but
    assets are already tenant_db-scoped so there's no cross-schema query."""
    q = q.strip()
    if len(q) < 2:
        return []
    stmt = (
        select(Asset)
        .where(
            Asset.name.ilike(f"%{q}%") | Asset.external_id.ilike(f"%{q}%") | Asset.ci_number.ilike(f"%{q}%")
        )
        .order_by(Asset.name)
        .limit(8)
    )
    result = await tenant_db.execute(stmt)
    return [
        {"id": a.id, "label": f"{a.ci_number}: {a.name}" + (f" ({a.external_id})" if a.external_id else "")}
        for a in result.scalars()
    ]


@router.post("/{ticket_id:int}/asset")
async def set_ticket_asset(
    ticket_id: int,
    asset_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        await service.update_asset(
            tenant_db,
            ticket,
            int(asset_id) if asset_id else None,
            changed_by_user_id=ctx.user.id,
        )
    return RedirectResponse(f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id:int}/approval/attach")
async def attach_approval_flow(
    ticket_id: int,
    flow_id: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await service.get_ticket(tenant_db, ticket_id)
    if ticket is not None and ticket.ticket_type == "change" and ticket.approval is None:
        await service.start_approval(tenant_db, ticket, int(flow_id) if flow_id else None)
    return RedirectResponse(f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id:int}/approval/decide")
async def decide_approval(
    ticket_id: int,
    decision: str = Form(...),
    comment: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    if decision not in ("approved", "rejected"):
        return RedirectResponse(f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)
    ticket = await service.get_ticket(tenant_db, ticket_id)
    if ticket is not None and ticket.approval is not None and ticket.approval.overall_status == "pending":
        step = await service.current_approval_step(tenant_db, ticket.approval)
        if step is not None and await service.is_eligible_approver(tenant_db, step, ctx.user.id):
            await service.decide_approval_step(
                tenant_db,
                ticket.approval,
                step,
                decision=decision,
                decided_by_user_id=ctx.user.id,
                comment=comment.strip(),
            )
    return RedirectResponse(f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{ticket_ref:ticket_ref}", response_class=HTMLResponse)
async def ticket_detail(
    request: Request,
    ticket_ref: str,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    ticket = await service.get_ticket_by_ref(tenant_db, ticket_ref)
    if ticket is None:
        return RedirectResponse("/tickets", status_code=status.HTTP_303_SEE_OTHER)
    document_links = await document_service.links_for(tenant_db, "ticket", ticket.id)
    # Not active_only: a ticket already sitting on a since-deactivated
    # status should still show it (and its color) in the stepper -- only
    # the "New ticket"/filter dropdowns need to hide deactivated ones.
    statuses = await service.list_statuses(tenant_db)
    status_labels = {s.key: s.label for s in statuses}

    flow_step_user_ids: set[int | None] = set()
    group_names: dict[int, str] = {}
    if ticket.approval and ticket.approval.flow:
        flow_step_user_ids = {s.approver_user_id for s in ticket.approval.flow.steps if s.approver_user_id}
        group_ids = {s.approver_group_id for s in ticket.approval.flow.steps if s.approver_group_id}
        if group_ids:
            groups_result = await tenant_db.execute(select(Group).where(Group.id.in_(group_ids)))
            group_names = {g.id: g.name for g in groups_result.scalars()}

    user_names = await resolve_user_names(
        {ticket.reporter_user_id, ticket.assignee_user_id}
        | {c.author_user_id for c in ticket.comments}
        | {sc.changed_by_user_id for sc in ticket.status_changes}
        | service.assignment_change_ids(ticket)
        | {ac.changed_by_user_id for ac in ticket.asset_changes}
        | {fc.changed_by_user_id for fc in ticket.field_changes}
        | ({d.decided_by_user_id for d in ticket.approval.decisions} if ticket.approval else set())
        | flow_step_user_ids
    )
    asset_names = await service.asset_names(tenant_db, {ticket.asset_id} | service.asset_change_ids(ticket))

    activity = service.build_activity(ticket)

    current_step = None
    can_decide = False
    flows = []
    # ticket.approval isn't change-exclusive -- a Service Catalog item can
    # attach one to an incident/vulnerability just as well (rain.modules.
    # catalog.service.submit_catalog_item), so this computes current_step/
    # can_decide off ticket.approval itself, not ticket_type. The manual
    # "attach a flow" affordance below stays change-only, though: that's
    # specifically changes' own "must have an approval flow" UX (enforced
    # at creation, see create_ticket below) -- an ordinary incident with
    # no approval shouldn't suddenly invite attaching one from its detail
    # page.
    if ticket.approval and ticket.approval.overall_status == "pending":
        current_step = await service.current_approval_step(tenant_db, ticket.approval)
        if current_step is not None:
            can_decide = await service.is_eligible_approver(tenant_db, current_step, ctx.user.id)
    elif ticket.ticket_type == "change" and ticket.approval is None:
        flows = await service.list_approval_flows(tenant_db)

    is_watching = await service.is_watching(tenant_db, ticket.id, ctx.user.id)
    escalation_webhook_id = await get_tenant_config(tenant_db, "escalation_webhook_id", None)

    return templates.TemplateResponse(
        request,
        "tickets/detail.html",
        {
            **nav,
            "ctx": ctx,
            "ticket": ticket,
            "statuses": statuses,
            "status_labels": status_labels,
            "severities": SEVERITIES,
            "document_links": document_links,
            "user_names": user_names,
            "asset_names": asset_names,
            "activity": activity,
            "current_step": current_step,
            "can_decide": can_decide,
            "flows": flows,
            "group_names": group_names,
            "is_watching": is_watching,
            "can_escalate": escalation_webhook_id is not None,
        },
    )


@router.get("/{ticket_id:int}/pdf")
async def ticket_pdf(
    ticket_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await service.get_ticket(tenant_db, ticket_id)
    if ticket is None:
        return RedirectResponse("/tickets", status_code=status.HTTP_303_SEE_OTHER)
    document_links = await document_service.links_for(tenant_db, "ticket", ticket_id)
    statuses = await service.list_statuses(tenant_db)
    status_labels = {s.key: s.label for s in statuses}
    user_names = await resolve_user_names(
        {ticket.reporter_user_id, ticket.assignee_user_id}
        | {c.author_user_id for c in ticket.comments}
        | {sc.changed_by_user_id for sc in ticket.status_changes}
        | service.assignment_change_ids(ticket)
        | {ac.changed_by_user_id for ac in ticket.asset_changes}
        | {fc.changed_by_user_id for fc in ticket.field_changes}
        | ({d.decided_by_user_id for d in ticket.approval.decisions} if ticket.approval else set())
    )
    asset_names = await service.asset_names(tenant_db, {ticket.asset_id} | service.asset_change_ids(ticket))
    pdf_bytes = render_pdf(
        "pdf/ticket.html",
        {
            "ticket": ticket,
            "document_links": document_links,
            "user_names": user_names,
            "asset_names": asset_names,
            "status_labels": status_labels,
            "activity": service.build_activity(ticket),
            "doc_kind": "Ticket",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    )
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{ticket.ticket_number}.pdf"'},
    )


@router.post("/{ticket_id:int}/comment")
async def add_comment(
    ticket_id: int,
    body: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    if body.strip():
        await service.add_comment(tenant_db, ticket_id, ctx.user.id, body.strip())
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id:int}/status")
async def change_status(
    ticket_id: int,
    new_status: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        await service.update_status(tenant_db, ticket, new_status, changed_by_user_id=ctx.user.id)
    return RedirectResponse(f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id:int}/watch/toggle")
async def toggle_watch(
    ticket_id: int,
    watching: str = Form(...),  # "1" | "0" -- current value the button already shows, so this is a set not a flip
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        if watching == "1":
            await service.add_watcher(tenant_db, ticket_id, ctx.user.id)
        else:
            await service.remove_watcher(tenant_db, ticket_id, ctx.user.id)
    return RedirectResponse(
        f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/{ticket_id:int}/escalate")
async def escalate_ticket(
    ticket_id: int,
    next: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Any signed-in user can escalate any ticket they can already see --
    unlike Mark closed/problematic (list quick-actions, require_login the
    same as this), there's no separate permission tier for "this is
    urgent," and the button is only ever rendered at all when the tenant
    has an escalation webhook configured (Admin > Branding). `next`
    lets the portal's per-row Escalate button (which has nowhere else
    useful to send someone with no session-based nav) return to the
    portal page instead of a ticket detail page it might not even be
    allowed to open (portal_require_auth off doesn't imply this visitor
    can view /tickets/<n> -- that's still require_login)."""
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        webhook_id = await get_tenant_config(tenant_db, "escalation_webhook_id", None)
        webhook = await tenant_db.get(WebhookConfig, webhook_id) if webhook_id else None
        if webhook is not None:
            await service.escalate_ticket(tenant_db, ticket, webhook, actor_user_id=ctx.user.id)
    if next:
        return RedirectResponse(safe_relative_path(next, default="/tickets"), status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(
        f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# ---------------------------------------------------- list quick-actions -

# The three actions below back the per-row [...] menu on the tickets list
# (rain.web.templates.tickets.list.html): unlike the detail-page actions
# above, they're fired from the list itself and must return there --
# `next` carries the list's current filter/sort/page query string so the
# redirect lands back on the same view rather than resetting it, guarded
# by safe_relative_path since it's user-suppliable input.


@router.post("/{ticket_id:int}/problematic/toggle")
async def toggle_problematic(
    ticket_id: int,
    is_problematic: str = Form(...),  # "1" | "0" -- current value the row already shows, so this is a set not a flip
    next: str = Form("/tickets"),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        await service.update_problematic(tenant_db, ticket, is_problematic == "1", changed_by_user_id=ctx.user.id)
    return RedirectResponse(safe_relative_path(next, default="/tickets"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id:int}/mark-closed")
async def mark_closed(
    ticket_id: int,
    next: str = Form("/tickets"),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        closed_status = await service.get_closed_status(tenant_db)
        if closed_status is not None:
            await service.update_status(tenant_db, ticket, closed_status.key, changed_by_user_id=ctx.user.id)
    return RedirectResponse(safe_relative_path(next, default="/tickets"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id:int}/mark-cancelled")
async def mark_cancelled(
    ticket_id: int,
    next: str = Form("/tickets"),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    # Changes-only, enforced server-side (not just hidden in the UI) --
    # "cancelled" isn't a meaningful state for incidents/vulnerabilities.
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None and ticket.ticket_type == "change":
        cancelled_status = await service.find_status_by_name(tenant_db, "cancelled")
        if cancelled_status is not None:
            await service.update_status(tenant_db, ticket, cancelled_status.key, changed_by_user_id=ctx.user.id)
    return RedirectResponse(safe_relative_path(next, default="/tickets"), status_code=status.HTTP_303_SEE_OTHER)


# ------------------------------------------------------------- export ----


@router.get("/export/run", response_class=HTMLResponse)
async def export_form(
    request: Request,
    profile_id: int | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    statuses = await service.list_statuses(tenant_db)
    profiles = await service.list_export_profiles(tenant_db)
    selected_profile = next((p for p in profiles if p.id == profile_id), None) if profile_id else None
    return templates.TemplateResponse(
        request,
        "tickets/export.html",
        {
            **nav,
            "ctx": ctx,
            "ticket_types": TICKET_TYPES,
            "statuses": statuses,
            "columns": merge_profile_columns(
                exporter.available_columns(), selected_profile.columns if selected_profile else None
            ),
            "profiles": profiles,
            "selected_profile_id": profile_id,
            "selected_fmt": selected_profile.format if selected_profile else "csv",
        },
    )


@router.post("/export/run")
async def export_run(
    request: Request,
    ticket_type: str = Form(""),
    ticket_status: str = Form(""),
    fmt: str = Form("csv"),
    save_as: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    columns = []
    for key in form.keys():
        if key.startswith("use_"):
            source = key[len("use_") :]
            header = str(form.get(f"header_{source}", source)).strip() or source
            columns.append({"source": source, "header": header, "order": int(form.get(f"order_{source}", 0) or 0)})
    columns.sort(key=lambda c: c["order"])
    if not columns:
        columns = [{"source": s, "header": h} for s, h in exporter.available_columns()]

    if save_as.strip():
        await service.save_export_profile(
            tenant_db, name=save_as.strip(), fmt=fmt, columns=columns, actor_id=ctx.user.id
        )

    rows = await exporter.build_rows(
        tenant_db, ticket_type=ticket_type or None, status=ticket_status or None, columns=columns
    )

    headers = [c["header"] for c in columns]
    if fmt == "json":
        body, media_type, filename = exporter.render_json(rows).encode("utf-8"), "application/json", "tickets-export.json"
    elif fmt == "xlsx":
        body = exporter.render_xlsx(rows, headers)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "tickets-export.xlsx"
    else:
        body, media_type, filename = exporter.render_csv(rows, headers).encode("utf-8"), "text/csv", "tickets-export.csv"

    return StreamingResponse(
        io.BytesIO(body),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------- rules ---


@router.get("/rules/all", response_class=HTMLResponse)
async def rules_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(TicketRule).order_by(TicketRule.sort_order)
    rule_page = await paginate(tenant_db, stmt, page=page)
    return templates.TemplateResponse(
        request,
        "tickets/rules.html",
        {
            **nav,
            "ctx": ctx,
            "page": rule_page,
            "ticket_types": TICKET_TYPES,
            "severities": SEVERITIES,
            "match_fields": MATCH_FIELDS,
            "test_result": None,
        },
    )


@router.post("/rules/all")
async def rules_create(
    name: str = Form(...),
    ticket_type: str = Form(...),
    match_field: str = Form("message"),
    pattern: str = Form(...),
    title_template: str = Form("{message}"),
    severity: str = Form("medium"),
    asset_match_field: str = Form(""),
    sort_order: int = Form(0),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    tenant_db.add(
        TicketRule(
            name=name.strip(),
            ticket_type=ticket_type,
            match_field=match_field,
            pattern=pattern,
            title_template=title_template or "{message}",
            severity=severity,
            asset_match_field=asset_match_field or None,
            sort_order=sort_order,
            created_by=ctx.user.id,
        )
    )
    await tenant_db.commit()
    return RedirectResponse("/tickets/rules/all", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/rules/{rule_id:int}/delete")
async def rules_delete(
    rule_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    rule = await tenant_db.get(TicketRule, rule_id)
    if rule is not None:
        await tenant_db.delete(rule)
        await tenant_db.commit()
    return RedirectResponse("/tickets/rules/all", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/rules/{rule_id:int}/test", response_class=HTMLResponse)
async def rules_test(
    request: Request,
    rule_id: int,
    sample: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    import re

    rule = await tenant_db.get(TicketRule, rule_id)
    matched = bool(rule and re.search(rule.pattern, sample))

    nav = await build_nav_context(ctx)
    stmt = select(TicketRule).order_by(TicketRule.sort_order)
    rule_page = await paginate(tenant_db, stmt, page=1)
    return templates.TemplateResponse(
        request,
        "tickets/rules.html",
        {
            **nav,
            "ctx": ctx,
            "page": rule_page,
            "ticket_types": TICKET_TYPES,
            "severities": SEVERITIES,
            "match_fields": MATCH_FIELDS,
            "test_result": {"rule_id": rule_id, "sample": sample, "matched": matched},
        },
    )


# --------------------------------------------------------- correlation ---


@router.get("/correlation-rules", response_class=HTMLResponse)
async def correlation_rules_list(
    request: Request,
    page: int = 1,
    prefill_pattern: str | None = None,
    prefill_match_field: str | None = None,
    prefill_ticket_type: str | None = None,
    prefill_group_by: str | None = None,
    prefill_threshold: int | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(CorrelationRule).order_by(CorrelationRule.sort_order)
    rule_page = await paginate(tenant_db, stmt, page=page)
    # "Correlate these" (tickets/live's selection menu) lands here with the
    # New rule modal pre-filled from the selected events instead of asking
    # the admin to retype a pattern they just saw stream by -- see
    # live.js's buildCorrelatePrefillUrl.
    prefill = (
        {
            "pattern": prefill_pattern,
            "match_field": prefill_match_field if prefill_match_field in MATCH_FIELDS else "message",
            "ticket_type": prefill_ticket_type if prefill_ticket_type in TICKET_TYPES else "incident",
            "group_by": prefill_group_by if prefill_group_by in GROUP_BY_FIELDS else "none",
            "threshold": prefill_threshold or 5,
        }
        if prefill_pattern
        else None
    )
    return templates.TemplateResponse(
        request,
        "tickets/correlation_rules.html",
        {
            **nav,
            "ctx": ctx,
            "page": rule_page,
            "ticket_types": TICKET_TYPES,
            "severities": SEVERITIES,
            "match_fields": MATCH_FIELDS,
            "group_by_fields": GROUP_BY_FIELDS,
            "rule_types": RULE_TYPES,
            "prefill": prefill,
        },
    )


_DEFAULT_TITLE_TEMPLATES = {
    "threshold": "{count} matching events in {window}m",
    "ml_anomaly": "Anomalous event detected (score {score})",
}


@router.post("/correlation-rules")
async def correlation_rules_create(
    name: str = Form(...),
    rule_type: str = Form("threshold"),
    ticket_type: str = Form(...),
    match_field: str = Form("message"),
    pattern: str = Form(...),
    group_by: str = Form("none"),
    threshold_count: int = Form(5),
    window_minutes: int = Form(5),
    title_template: str = Form(""),
    severity: str = Form("medium"),
    asset_match_field: str = Form(""),
    sort_order: int = Form(0),
    ml_score_threshold: float = Form(0.7),
    ml_warmup_count: int = Form(250),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    if rule_type not in RULE_TYPES:
        rule_type = "threshold"
    tenant_db.add(
        CorrelationRule(
            name=name.strip(),
            rule_type=rule_type,
            ticket_type=ticket_type,
            match_field=match_field,
            pattern=pattern,
            group_by=group_by,
            threshold_count=max(2, threshold_count),
            window_minutes=max(1, window_minutes),
            title_template=title_template.strip() or _DEFAULT_TITLE_TEMPLATES[rule_type],
            severity=severity,
            asset_match_field=asset_match_field or None,
            sort_order=sort_order,
            # min(1, ...) so a typo/blank field can't produce a threshold
            # of 0 (every event would be "anomalous") or a warmup of 0
            # (a rule fires on its very first, baseline-free event).
            ml_score_threshold=min(1.0, max(0.0, ml_score_threshold)),
            ml_warmup_count=max(1, ml_warmup_count),
            created_by=ctx.user.id,
        )
    )
    await tenant_db.commit()
    return RedirectResponse("/tickets/correlation-rules", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/correlation-rules/{rule_id:int}/delete")
async def correlation_rules_delete(
    rule_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    rule = await tenant_db.get(CorrelationRule, rule_id)
    if rule is not None:
        await tenant_db.delete(rule)
        await tenant_db.commit()
    return RedirectResponse("/tickets/correlation-rules", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/correlation-rules/{rule_id:int}/toggle")
async def correlation_rules_toggle(
    rule_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    rule = await tenant_db.get(CorrelationRule, rule_id)
    if rule is not None:
        rule.is_active = not rule.is_active
        await tenant_db.commit()
    return RedirectResponse("/tickets/correlation-rules", status_code=status.HTTP_303_SEE_OTHER)


# ----------------------------------------------------- platform events ---


@router.get("/platform-events", response_class=HTMLResponse)
async def platform_events_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = (
        select(PlatformEventRule)
        .options(selectinload(PlatformEventRule.actions))
        .order_by(PlatformEventRule.sort_order)
    )
    rule_page = await paginate(tenant_db, stmt, page=page)
    return templates.TemplateResponse(
        request,
        "tickets/platform_events.html",
        {
            **nav,
            "ctx": ctx,
            "page": rule_page,
            "trigger_events": platform_events.TRIGGER_EVENTS,
            "trigger_event_labels": dict(platform_events.TRIGGER_EVENTS),
            "match_fields": platform_events.MATCH_FIELDS,
        },
    )


@router.post("/platform-events")
async def platform_events_create(
    name: str = Form(...),
    trigger_event: str = Form(...),
    match_field: str = Form("title"),
    pattern: str = Form(...),
    sort_order: int = Form(0),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    rule = PlatformEventRule(
        name=name.strip(),
        trigger_event=trigger_event,
        match_field=match_field,
        pattern=pattern,
        sort_order=sort_order,
        created_by=ctx.user.id,
    )
    tenant_db.add(rule)
    await tenant_db.flush()
    rule_id = rule.id
    await tenant_db.commit()
    return RedirectResponse(f"/tickets/platform-events/{rule_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/platform-events/{rule_id:int}/delete")
async def platform_events_delete(
    rule_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_admin)
):
    rule = await tenant_db.get(PlatformEventRule, rule_id)
    if rule is not None:
        await tenant_db.delete(rule)
        await tenant_db.commit()
    return RedirectResponse("/tickets/platform-events", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/platform-events/{rule_id:int}", response_class=HTMLResponse)
async def platform_event_detail(
    request: Request,
    rule_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = (
        select(PlatformEventRule).where(PlatformEventRule.id == rule_id).options(selectinload(PlatformEventRule.actions))
    )
    rule = (await tenant_db.execute(stmt)).scalar_one_or_none()
    if rule is None:
        return RedirectResponse("/tickets/platform-events", status_code=status.HTTP_303_SEE_OTHER)
    channels = list((await tenant_db.execute(select(NotificationChannel).order_by(NotificationChannel.name))).scalars())
    documents = await document_service.list_documents(tenant_db)
    assets = await asset_service.list_assets(tenant_db)
    webhooks = await webhook_service.list_webhooks(tenant_db)
    return templates.TemplateResponse(
        request,
        "tickets/platform_event_detail.html",
        {
            **nav,
            "ctx": ctx,
            "rule": rule,
            "trigger_events": platform_events.TRIGGER_EVENTS,
            "trigger_event_labels": dict(platform_events.TRIGGER_EVENTS),
            "match_fields": platform_events.MATCH_FIELDS,
            "action_types": platform_events.ACTION_TYPES,
            "channels": channels,
            "documents": documents,
            "assets": assets,
            "webhooks": webhooks,
            "webhook_names": {w.id: w.name for w in webhooks},
        },
    )


@router.post("/platform-events/{rule_id:int}/edit")
async def platform_event_edit(
    rule_id: int,
    name: str = Form(...),
    trigger_event: str = Form(...),
    match_field: str = Form("title"),
    pattern: str = Form(...),
    sort_order: int = Form(0),
    is_active: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    rule = await tenant_db.get(PlatformEventRule, rule_id)
    if rule is not None:
        rule.name = name.strip()
        rule.trigger_event = trigger_event
        rule.match_field = match_field
        rule.pattern = pattern
        rule.sort_order = sort_order
        rule.is_active = is_active
        await tenant_db.commit()
    return RedirectResponse(f"/tickets/platform-events/{rule_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/platform-events/{rule_id:int}/actions")
async def platform_event_action_create(
    request: Request,
    rule_id: int,
    action_type: str = Form(...),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    form = await request.form()
    if action_type in ("notify_slack", "notify_email"):
        channel_id = form.get("channel_id")
        config = {"channel_id": int(channel_id)} if channel_id else {}
    elif action_type == "webhook":
        webhook_id = form.get("webhook_config_id")
        config = {"webhook_id": int(webhook_id)} if webhook_id else {}
    elif action_type == "attach_document":
        document_id = form.get("document_id")
        config = {"document_id": int(document_id)} if document_id else {}
    elif action_type == "attach_asset":
        asset_id = form.get("asset_id")
        config = {"asset_id": int(asset_id)} if asset_id else {}
    elif action_type == "add_watcher":
        email = (form.get("watcher_email") or "").strip()
        watcher_user_id = form.get("watcher_user_id")
        # Email wins if both were somehow filled in -- matches
        # add_watcher_by_email/add_watcher's own "email first" order in
        # platform_events._run_action.
        config = {"email": email} if email else ({"user_id": int(watcher_user_id)} if watcher_user_id else {})
    else:
        config = {}
    tenant_db.add(PlatformEventAction(rule_id=rule_id, action_type=action_type, config=config))
    await tenant_db.commit()
    return RedirectResponse(f"/tickets/platform-events/{rule_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/platform-events/{rule_id:int}/actions/{action_id:int}/delete")
async def platform_event_action_delete(
    rule_id: int,
    action_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    action = await tenant_db.get(PlatformEventAction, action_id)
    if action is not None:
        await tenant_db.delete(action)
        await tenant_db.commit()
    return RedirectResponse(f"/tickets/platform-events/{rule_id}", status_code=status.HTTP_303_SEE_OTHER)
