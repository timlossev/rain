from __future__ import annotations

import io
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.core.pagination import paginate
from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
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
)
from rain.modules.assets import service as asset_service
from rain.modules.documents import service as document_service
from rain.modules.tickets import exporter, platform_events, service
from rain.modules.tickets.correlation import GROUP_BY_FIELDS
from rain.modules.tickets.schemas import MATCH_FIELDS, SEVERITIES, TICKET_TYPES
from rain.web.nav import build_nav_context
from rain.web.pdf import render_pdf
from rain.web.safe_redirect import safe_relative_path
from rain.web.templating import templates

router = APIRouter(prefix="/tickets")


# ------------------------------------------------------------- tickets ---


@router.get("", response_class=HTMLResponse)
async def list_tickets(
    request: Request,
    ticket_type: str | None = None,
    ticket_status: str | None = None,
    assigned: str | None = None,  # "me" | "unassigned" | None
    chronic: str | None = None,  # "1" | None
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
        chronic_only=bool(chronic),
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
            "selected_chronic": bool(chronic),
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
        start_date=date.fromisoformat(start_date) if start_date else None,
        end_date=date.fromisoformat(end_date) if end_date else None,
        assignee_user_id=int(assignee_user_id) if assignee_user_id else None,
        reporter_user_id=ctx.user.id,
    )
    if ticket_type == "change":
        await service.start_approval(tenant_db, ticket, int(approval_flow_id) if approval_flow_id else None)
    return RedirectResponse(f"/tickets/{ticket.id}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


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
        .where((Asset.name.ilike(f"%{q}%")) | (Asset.external_id.ilike(f"%{q}%")))
        .order_by(Asset.name)
        .limit(8)
    )
    result = await tenant_db.execute(stmt)
    return [{"id": a.id, "label": f"{a.name} ({a.external_id})" if a.external_id else a.name} for a in result.scalars()]


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
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


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
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


def _build_activity(ticket: Ticket) -> list[dict]:
    """Comments, status changes, assignment changes, asset changes, and
    (change tickets only) approval decisions interleaved into one
    chronological feed ("Activity"), each tagged with its kind so the
    caller (screen or PDF) can render them differently. Shared so the PDF
    export shows the same unified feed as the ticket detail screen instead
    of drifting apart."""
    approval_entries = (
        [{"kind": "approval_decision", "at": d.created_at, "item": d} for d in ticket.approval.decisions]
        if ticket.approval
        else []
    )
    return sorted(
        [{"kind": "comment", "at": c.created_at, "item": c} for c in ticket.comments]
        + [{"kind": "status_change", "at": sc.created_at, "item": sc} for sc in ticket.status_changes]
        + [{"kind": "assignment_change", "at": ac.created_at, "item": ac} for ac in ticket.assignment_changes]
        + [{"kind": "asset_change", "at": ac.created_at, "item": ac} for ac in ticket.asset_changes]
        + approval_entries,
        key=lambda entry: entry["at"] or datetime.min.replace(tzinfo=timezone.utc),
    )


def _assignment_change_ids(ticket: Ticket) -> set[int | None]:
    ids: set[int | None] = set()
    for ac in ticket.assignment_changes:
        ids |= {ac.changed_by_user_id, ac.from_assignee_user_id, ac.to_assignee_user_id}
    return ids


async def _asset_names(tenant_db: AsyncSession, asset_ids: set[int | None]) -> dict[int, str]:
    """Batched name lookup for the asset picker's initial label and the
    activity feed's asset-change entries -- same shape as
    rain.core.user_names.resolve_user_names, but assets live in this same
    tenant_db session (no cross-schema query needed, unlike users)."""
    ids = {i for i in asset_ids if i is not None}
    if not ids:
        return {}
    result = await tenant_db.execute(select(Asset).where(Asset.id.in_(ids)))
    return {a.id: a.name for a in result.scalars()}


def _asset_change_ids(ticket: Ticket) -> set[int | None]:
    ids: set[int | None] = set()
    for ac in ticket.asset_changes:
        ids |= {ac.from_asset_id, ac.to_asset_id}
    return ids


@router.get("/{ticket_id:int}", response_class=HTMLResponse)
async def ticket_detail(
    request: Request,
    ticket_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    ticket = await service.get_ticket(tenant_db, ticket_id)
    if ticket is None:
        return RedirectResponse("/tickets", status_code=status.HTTP_303_SEE_OTHER)
    document_links = await document_service.links_for(tenant_db, "ticket", ticket_id)
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
        | _assignment_change_ids(ticket)
        | {ac.changed_by_user_id for ac in ticket.asset_changes}
        | ({d.decided_by_user_id for d in ticket.approval.decisions} if ticket.approval else set())
        | flow_step_user_ids
    )
    asset_names = await _asset_names(tenant_db, {ticket.asset_id} | _asset_change_ids(ticket))

    activity = _build_activity(ticket)

    current_step = None
    can_decide = False
    flows = []
    if ticket.ticket_type == "change":
        if ticket.approval and ticket.approval.overall_status == "pending":
            current_step = await service.current_approval_step(tenant_db, ticket.approval)
            if current_step is not None:
                can_decide = await service.is_eligible_approver(tenant_db, current_step, ctx.user.id)
        elif ticket.approval is None:
            flows = await service.list_approval_flows(tenant_db)

    return templates.TemplateResponse(
        request,
        "tickets/detail.html",
        {
            **nav,
            "ctx": ctx,
            "ticket": ticket,
            "statuses": statuses,
            "status_labels": status_labels,
            "document_links": document_links,
            "user_names": user_names,
            "asset_names": asset_names,
            "activity": activity,
            "current_step": current_step,
            "can_decide": can_decide,
            "flows": flows,
            "group_names": group_names,
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
        | _assignment_change_ids(ticket)
        | {ac.changed_by_user_id for ac in ticket.asset_changes}
        | ({d.decided_by_user_id for d in ticket.approval.decisions} if ticket.approval else set())
    )
    asset_names = await _asset_names(tenant_db, {ticket.asset_id} | _asset_change_ids(ticket))
    pdf_bytes = render_pdf(
        "pdf/ticket.html",
        {
            "ticket": ticket,
            "document_links": document_links,
            "user_names": user_names,
            "asset_names": asset_names,
            "status_labels": status_labels,
            "activity": _build_activity(ticket),
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
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------- list quick-actions -

# The three actions below back the per-row [...] menu on the tickets list
# (rain.web.templates.tickets.list.html): unlike the detail-page actions
# above, they're fired from the list itself and must return there --
# `next` carries the list's current filter/sort/page query string so the
# redirect lands back on the same view rather than resetting it, guarded
# by safe_relative_path since it's user-suppliable input.


@router.post("/{ticket_id:int}/chronic/toggle")
async def toggle_chronic(
    ticket_id: int,
    is_chronic: str = Form(...),  # "1" | "0" -- current value the row already shows, so this is a set not a flip
    next: str = Form("/tickets"),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        await service.update_chronic(tenant_db, ticket, is_chronic == "1")
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
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    statuses = await service.list_statuses(tenant_db)
    return templates.TemplateResponse(
        request,
        "tickets/export.html",
        {
            **nav,
            "ctx": ctx,
            "ticket_types": TICKET_TYPES,
            "statuses": statuses,
            "columns": exporter.available_columns(),
        },
    )


@router.post("/export/run")
async def export_run(
    request: Request,
    ticket_type: str = Form(""),
    ticket_status: str = Form(""),
    fmt: str = Form("csv"),
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
    _: CurrentUser = Depends(require_login),
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
    _: CurrentUser = Depends(require_login),
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
    rule_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_login)
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
    _: CurrentUser = Depends(require_login),
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
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    stmt = select(CorrelationRule).order_by(CorrelationRule.sort_order)
    rule_page = await paginate(tenant_db, stmt, page=page)
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
        },
    )


@router.post("/correlation-rules")
async def correlation_rules_create(
    name: str = Form(...),
    ticket_type: str = Form(...),
    match_field: str = Form("message"),
    pattern: str = Form(...),
    group_by: str = Form("none"),
    threshold_count: int = Form(5),
    window_minutes: int = Form(5),
    title_template: str = Form("{count} matching events in {window}m"),
    severity: str = Form("medium"),
    asset_match_field: str = Form(""),
    sort_order: int = Form(0),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    tenant_db.add(
        CorrelationRule(
            name=name.strip(),
            ticket_type=ticket_type,
            match_field=match_field,
            pattern=pattern,
            group_by=group_by,
            threshold_count=max(2, threshold_count),
            window_minutes=max(1, window_minutes),
            title_template=title_template or "{count} matching events in {window}m",
            severity=severity,
            asset_match_field=asset_match_field or None,
            sort_order=sort_order,
            created_by=ctx.user.id,
        )
    )
    await tenant_db.commit()
    return RedirectResponse("/tickets/correlation-rules", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/correlation-rules/{rule_id:int}/delete")
async def correlation_rules_delete(
    rule_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_login)
):
    rule = await tenant_db.get(CorrelationRule, rule_id)
    if rule is not None:
        await tenant_db.delete(rule)
        await tenant_db.commit()
    return RedirectResponse("/tickets/correlation-rules", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/correlation-rules/{rule_id:int}/toggle")
async def correlation_rules_toggle(
    rule_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_login)
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
    _: CurrentUser = Depends(require_login),
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
    _: CurrentUser = Depends(require_login),
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
    rule_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_login)
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
    _: CurrentUser = Depends(require_login),
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
    return templates.TemplateResponse(
        request,
        "tickets/platform_event_detail.html",
        {
            **nav,
            "ctx": ctx,
            "rule": rule,
            "trigger_event_labels": dict(platform_events.TRIGGER_EVENTS),
            "action_types": platform_events.ACTION_TYPES,
            "channels": channels,
            "documents": documents,
            "assets": assets,
        },
    )


@router.post("/platform-events/{rule_id:int}/actions")
async def platform_event_action_create(
    request: Request,
    rule_id: int,
    action_type: str = Form(...),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    if action_type in ("notify_slack", "notify_email"):
        channel_id = form.get("channel_id")
        config = {"channel_id": int(channel_id)} if channel_id else {}
    elif action_type == "webhook":
        config = {
            "url": str(form.get("webhook_url", "")).strip(),
            "payload_template": str(form.get("payload_template", "")).strip() or "{}",
        }
    elif action_type == "attach_document":
        document_id = form.get("document_id")
        config = {"document_id": int(document_id)} if document_id else {}
    elif action_type == "attach_asset":
        asset_id = form.get("asset_id")
        config = {"asset_id": int(asset_id)} if asset_id else {}
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
    _: CurrentUser = Depends(require_login),
):
    action = await tenant_db.get(PlatformEventAction, action_id)
    if action is not None:
        await tenant_db.delete(action)
        await tenant_db.commit()
    return RedirectResponse(f"/tickets/platform-events/{rule_id}", status_code=status.HTTP_303_SEE_OTHER)
