from __future__ import annotations

import io
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.convertors import Convertor, register_url_convertor

from rain.core.export_columns import merge_profile_columns
from rain.core.field_pack import sniff_columns
from rain.core.pagination import paginate
from rain.core.rbac import require_admin, require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.core.tenant_config import get_tenant_config, get_tenant_configs, set_tenant_config
from rain.core.user_names import is_assignable_user, list_assignable_users, resolve_user_names
from rain.db.base import control_session
from rain.db.control_models import User
from rain.db.tenant_models import (
    Asset,
    CustomField,
    Group,
    GroupMembership,
    NotificationChannel,
    PlatformEventAction,
    PlatformEventRule,
    Ticket,
    TicketRule,
    WebhookConfig,
)
from rain.modules.assets import service as asset_service
from rain.modules.assets.schemas import coerce_field_value
from rain.modules.documents import service as document_service
from rain.modules.tickets import exporter, importer, platform_events, rootcause, service
from rain.modules.tickets.rules import (
    DEFAULT_ML_ALGORITHM,
    GROUP_BY_FIELDS,
    ML_ALGORITHMS,
    PROMOTION_TYPES,
    bulk_rule_training_summary,
    rule_training_status,
)
from rain.modules.tickets.schemas import MATCH_FIELDS, SEVERITIES, TICKET_TYPES
from rain.modules.webhooks import service as webhook_service
from rain.web.nav import build_nav_context
from rain.web.pdf import render_pdf
from rain.web.safe_redirect import safe_relative_path
from rain.web.templating import templates
from rain.web.uploads import import_stash_path

# Same shape the manual "New custom field" form's field_key
# `pattern="[a-z][a-z0-9_]*"` requires -- rain.core.field_pack.slugify_key
# already produces this, but a field pack's preview screen lets an admin
# hand-edit the guessed key before commit, so it's re-validated here too.
_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


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
    asset_id: int | None = None,
    assigned: str | None = None,  # "me" | "unassigned" | None
    problematic: str | None = None,  # "1" | None
    prioritized: str | None = None,  # "1" | None
    sort: str | None = None,
    dir: str = "desc",
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    dir = "asc" if dir == "asc" else "desc"
    # No ticket_status in the URL at all (a bare /tickets, or the very
    # first visit) defaults to "active" -- every status except whichever
    # the tenant's flagged is_closed -- rather than showing every closed
    # ticket ever, forever, on the landing view. ticket_status="" (the
    # "All statuses" dropdown option, which always submits the param even
    # when blank) explicitly opts back into everything; a real status key
    # (including a closed one) filters to exactly that, same as before.
    effective_status = "active" if ticket_status is None else ticket_status
    stmt = service.ticket_list_stmt(
        ticket_type=ticket_type,
        status=effective_status,
        asset_id=asset_id,
        assigned_to=ctx.user.id if assigned == "me" else None,
        unassigned=assigned == "unassigned",
        problematic_only=bool(problematic),
        prioritized_only=bool(prioritized),
        sort=sort,
        direction=dir,
    )
    page_size = await get_tenant_config(tenant_db, "default_page_size")
    ticket_page = await paginate(tenant_db, stmt, page=page, page_size=page_size)
    statuses = await service.list_statuses(tenant_db)
    status_colors = {s.key: s.color for s in statuses}
    user_names = await resolve_user_names({t.assignee_user_id for t in ticket_page.items})
    selected_asset = await asset_service.get_asset(tenant_db, asset_id) if asset_id else None
    # The same two conditions the ticket detail page's own top-right
    # button row uses for Escalate/Watch, computed here for the row
    # menu's "Analyze root cause"/Escalate/Watch items so they stay
    # available from exactly the same conditions either place -- see
    # tickets/detail.html and this module's ticket_detail.
    escalation_settings = await get_tenant_configs(tenant_db, ["escalation_webhook_id", "escalate_button_label"])
    watching_ids = await service.watching_ticket_ids(tenant_db, {t.id for t in ticket_page.items}, ctx.user.id)
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
            "selected_asset_id": asset_id,
            "selected_asset_name": selected_asset.name if selected_asset else "",
            "selected_assigned": assigned,
            "selected_problematic": bool(problematic),
            "selected_prioritized": bool(prioritized),
            "selected_sort": sort if sort in service.SORTABLE_COLUMNS else "created_at",
            "selected_dir": dir,
            "user_names": user_names,
            "can_escalate": escalation_settings["escalation_webhook_id"] is not None,
            "escalate_label": escalation_settings["escalate_button_label"],
            "watching_ids": watching_ids,
        },
    )


# Hard cap on how many tickets a Kanban board renders at once. Unlike the
# table view, this has no pagination -- the whole point of a board is
# seeing everything matching the current filters in one place, not
# paging through it column by column. 500 is generous for what a board
# can usefully show anyway (a column holding hundreds of cards stops
# being a board); truncated=True tells the template to say so rather
# than silently showing a partial picture.
_KANBAN_TICKET_CAP = 500


@router.get("/kanban", response_class=HTMLResponse)
async def kanban_board(
    request: Request,
    ticket_type: str | None = None,
    ticket_status: str | None = None,
    asset_id: int | None = None,
    assigned: str | None = None,  # "me" | "unassigned" | None
    problematic: str | None = None,  # "1" | None
    prioritized: str | None = None,  # "1" | None
    group_by: str = "status",  # "status" | "assignee"
    assignee_group: int | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Same filters, same service.ticket_list_stmt, as list_tickets above
    -- just grouped into columns instead of table rows, so the two views
    can never disagree about which tickets match a given filter set. No
    sort control here (column position already conveys grouping; each
    column is created_at desc, ticket_list_stmt's own default) and no
    pagination -- see _KANBAN_TICKET_CAP.

    group_by picks what the columns *are*, independent of every filter
    above: "status" (default) groups by this tenant's own TicketStatus
    set, same as always; "assignee" groups by who's carrying each ticket
    instead, for a workload-at-a-glance view -- one column per this
    tenant's assignable users (rain.core.user_names.list_assignable_users,
    the same candidate set the assignee picker itself offers) plus a
    leading "Unassigned" column. Dragging a card between assignee columns
    reassigns it (POST .../kanban-assignee below) the same optimistic way
    dragging between status columns changes its status.

    assignee_group (a Group.id, "assignee" mode only) narrows that column
    set further, to just one tenant Group's own members -- every
    assignable user can otherwise be a lot of columns. Still one column
    per *person*, not per group: dragging still assigns to that specific
    individual, unchanged, this just changes which individuals get
    columns to begin with. A ticket already assigned to someone outside
    the selected group still shows, same extra-column-not-a-drop-target
    treatment as someone no longer assignable to this tenant at all."""
    nav = await build_nav_context(ctx)
    group_by = group_by if group_by in ("status", "assignee") else "status"
    effective_status = "active" if ticket_status is None else ticket_status
    stmt = service.ticket_list_stmt(
        ticket_type=ticket_type,
        status=effective_status,
        asset_id=asset_id,
        assigned_to=ctx.user.id if assigned == "me" else None,
        unassigned=assigned == "unassigned",
        problematic_only=bool(problematic),
        prioritized_only=bool(prioritized),
    ).limit(_KANBAN_TICKET_CAP + 1)
    result = await tenant_db.execute(stmt)
    tickets = list(result.scalars())
    truncated = len(tickets) > _KANBAN_TICKET_CAP
    tickets = tickets[:_KANBAN_TICKET_CAP]

    statuses = await service.list_statuses(tenant_db)
    columns: dict[str, list[Ticket]] = {s.key: [] for s in statuses}
    # A ticket can sit on a status key the tenant has since deleted (see
    # TicketStatus's own docstring on why Ticket.status is a plain string,
    # not a real FK) -- still shown, in its own extra column, rather than
    # silently dropped off the board.
    for t in tickets:
        columns.setdefault(t.status, []).append(t)
    known_keys = {s.key for s in statuses}
    extra_status_keys = sorted(k for k in columns if k not in known_keys)

    assignee_users: list[User] = []
    assignee_columns: dict[str, list[Ticket]] = {}
    extra_assignee_ids: list[int] = []
    assignee_groups: list[Group] = []
    if group_by == "assignee":
        assignee_groups = list((await tenant_db.execute(select(Group).order_by(Group.name))).scalars())
        assignee_users = await list_assignable_users(ctx.active_tenant.id)
        if assignee_group is not None:
            member_ids = set(
                (
                    await tenant_db.execute(
                        select(GroupMembership.user_id).where(GroupMembership.group_id == assignee_group)
                    )
                ).scalars()
            )
            assignee_users = [u for u in assignee_users if u.id in member_ids]
        known_user_ids = {u.id for u in assignee_users}
        assignee_columns = {"unassigned": []}
        for u in assignee_users:
            assignee_columns[str(u.id)] = []
        for t in tickets:
            if t.assignee_user_id is None:
                assignee_columns["unassigned"].append(t)
            elif t.assignee_user_id in known_user_ids:
                assignee_columns[str(t.assignee_user_id)].append(t)
            else:
                # Assigned to someone no longer assignable to this tenant
                # (deactivated, or moved off it since) -- same "extra
                # column rather than silently dropped" treatment
                # extra_status_keys gives an orphaned status above.
                assignee_columns.setdefault(str(t.assignee_user_id), []).append(t)
                if t.assignee_user_id not in extra_assignee_ids:
                    extra_assignee_ids.append(t.assignee_user_id)

    selected_asset = await asset_service.get_asset(tenant_db, asset_id) if asset_id else None
    escalation_settings = await get_tenant_configs(tenant_db, ["escalation_webhook_id", "escalate_button_label"])
    user_names = await resolve_user_names({t.assignee_user_id for t in tickets} | set(extra_assignee_ids))
    watching_ids = await service.watching_ticket_ids(tenant_db, {t.id for t in tickets}, ctx.user.id)

    return templates.TemplateResponse(
        request,
        "tickets/kanban.html",
        {
            **nav,
            "ctx": ctx,
            "ticket_types": TICKET_TYPES,
            "statuses": statuses,
            "extra_status_keys": extra_status_keys,
            "columns": columns,
            "selected_group_by": group_by,
            "assignee_groups": assignee_groups,
            "selected_assignee_group": assignee_group,
            "assignee_users": assignee_users,
            "assignee_columns": assignee_columns,
            "extra_assignee_ids": extra_assignee_ids,
            "truncated": truncated,
            "selected_type": ticket_type,
            "selected_status": ticket_status,
            "selected_asset_id": asset_id,
            "selected_asset_name": selected_asset.name if selected_asset else "",
            "selected_assigned": assigned,
            "selected_problematic": bool(problematic),
            "selected_prioritized": bool(prioritized),
            "user_names": user_names,
            "can_escalate": escalation_settings["escalation_webhook_id"] is not None,
            "escalate_label": escalation_settings["escalate_button_label"],
            "watching_ids": watching_ids,
        },
    )


@router.post("/{ticket_id:int}/kanban-status")
async def kanban_update_status(
    ticket_id: int,
    new_status: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """The Kanban board's drag-and-drop move: same service.update_status
    call the status-stepper's /status route makes (below), but returns
    JSON instead of redirecting -- the board moves the card in the DOM
    itself rather than reloading the whole page after every drag. No
    approval-reset confirm to replicate here: unlike the severity/title/
    assignee/asset edit forms (tickets/detail.html's approval_will_reset),
    a plain status change never nullifies a change's collected approvals,
    on this route or /status -- see service.update_status."""
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is None:
        return JSONResponse({"ok": False, "error": "Ticket not found."}, status_code=404)
    ok = await service.update_status(tenant_db, ticket, new_status, changed_by_user_id=ctx.user.id)
    if not ok:
        return JSONResponse({"ok": False, "error": "Not a valid status."}, status_code=400)
    return {"ok": True, "status": ticket.status}


@router.post("/{ticket_id:int}/kanban-assignee")
async def kanban_update_assignee(
    ticket_id: int,
    new_assignee_user_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Kanban's "group by assignee" view (kanban_board above): dragging a
    card into a different assignee column, or into "Unassigned", reassigns
    it -- same service.update_assignee call the ticket detail page's own
    /assign route makes (and the same is_assignable_user re-check that
    route's own comment explains: the board only ever offers this
    tenant's own assignable users as columns to begin with, but a crafted
    POST could still name an arbitrary id, so this is what actually
    enforces it), just returning JSON instead of redirecting -- the board
    moves the card in the DOM itself, mirroring kanban_update_status."""
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is None:
        return JSONResponse({"ok": False, "error": "Ticket not found."}, status_code=404)
    new_id = int(new_assignee_user_id) if new_assignee_user_id else None
    if new_id is not None and not await is_assignable_user(new_id, ctx.active_tenant.id):
        return JSONResponse({"ok": False, "error": "Not assignable to this tenant."}, status_code=400)
    await service.update_assignee(tenant_db, ticket, new_id, changed_by_user_id=ctx.user.id)
    names = await resolve_user_names({new_id}) if new_id is not None else {}
    return {"ok": True, "assignee_user_id": new_id, "assignee_name": names.get(new_id, "Unassigned")}


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
        prefill_title = f"{event.program or event.host or 'Event'}: {event.message[:200]}" if event else ""
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
    fields = await service.ticket_fields(tenant_db)

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
            "fields": fields,
            "values": {},
            "error": error,
        },
    )


@router.post("")
async def create_ticket(
    request: Request,
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

    # Custom field capture: tenant-wide (rain.modules.tickets.service.
    # ticket_fields, not filtered by ticket_type), same "read the field
    # list, then only trust field_<id> keys it names" pattern as
    # rain.modules.assets.router.create_asset -- never trusts arbitrary
    # form keys directly.
    fields = await service.ticket_fields(tenant_db)
    if fields:
        form = await request.form()
        values = {}
        for f in fields:
            raw = form.get(f"field_{f.id}")
            values[f.id] = coerce_field_value(f.field_type, raw if isinstance(raw, str) else None)
        await service.set_ticket_field_values(tenant_db, ticket, values)
        await tenant_db.commit()

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
    new_assignee_id = int(assignee_user_id) if assignee_user_id else None
    # search_assignable_users only ever offers this tenant's own users
    # (plus internal_admin), but that's just what the picker shows --
    # nothing stops a crafted POST from naming a different tenant's user
    # id outright, which would otherwise both leak that user's display
    # name back onto this ticket and subscribe them as a watcher on this
    # tenant's ticket traffic. Re-applying the same scoping check server-
    # side here is what actually enforces it.
    if ticket is not None and (new_assignee_id is None or await is_assignable_user(new_assignee_id, ctx.active_tenant.id)):
        await service.update_assignee(
            tenant_db,
            ticket,
            new_assignee_id,
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
    escalation_settings = await get_tenant_configs(tenant_db, ["escalation_webhook_id", "escalate_button_label"])

    fields = await service.ticket_fields(tenant_db)
    field_values = {fv.field_id: fv.value for fv in ticket.field_values}

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
            "can_escalate": escalation_settings["escalation_webhook_id"] is not None,
            "escalate_label": escalation_settings["escalate_button_label"],
            "fields": fields,
            "field_values": field_values,
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
    fields = await service.ticket_fields(tenant_db)
    values = {fv.field_id: fv.value for fv in ticket.field_values}
    pdf_bytes = render_pdf(
        "pdf/ticket.html",
        {
            "ticket": ticket,
            "document_links": document_links,
            "user_names": user_names,
            "asset_names": asset_names,
            "status_labels": status_labels,
            "activity": service.build_activity(ticket),
            "fields": fields,
            "values": values,
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


@router.post("/{ticket_id:int}/fields")
async def save_fields(
    request: Request,
    ticket_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """One bulk save for every custom field value on this ticket's detail
    page -- unlike severity/title's per-field data-inline-edit JS, there's
    no reason to round-trip per field here, so the Custom fields card is
    just a plain form posting here."""
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        form = await request.form()
        fields = await service.ticket_fields(tenant_db)
        values = {}
        for f in fields:
            raw = form.get(f"field_{f.id}")
            values[f.id] = coerce_field_value(f.field_type, raw if isinstance(raw, str) else None)
        await service.set_ticket_field_values(tenant_db, ticket, values)
        await tenant_db.commit()
    return RedirectResponse(
        f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER
    )


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
    next: str = Form(""),
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
    if next:
        return RedirectResponse(safe_relative_path(next, default="/tickets"), status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(
        f"/tickets/{ticket.ticket_number if ticket else ticket_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/{ticket_id:int}/escalate")
async def escalate_ticket(
    request: Request,
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
    has an escalation webhook configured (Admin > Branding).

    Two response shapes, chosen by whether `next` was sent, not by
    content negotiation: the portal's own per-row Escalate button (which
    has nowhere else useful to send someone with no session-based nav,
    and no modal to show a result in) always sends `next` and gets the
    original redirect-back-to-`next` behavior -- `next` lets it return to
    the portal page instead of a ticket detail page it might not even be
    allowed to open (portal_require_auth off doesn't imply this visitor
    can view /tickets/<n> -- that's still require_login). Every other
    caller (the ticket detail page's own button, the tickets list row
    menu, the Kanban card menu) is a plain JS-driven button, not a real
    form submission -- data-escalate-ticket in app.js -- so it never
    sends `next` at all, and gets the fragment (tickets/
    _escalate_result.html) that populates their shared modal instead."""
    ticket = await tenant_db.get(Ticket, ticket_id)
    outcome = None
    error = None
    if ticket is None:
        error = "Ticket not found."
    else:
        webhook_id = await get_tenant_config(tenant_db, "escalation_webhook_id", None)
        webhook = await tenant_db.get(WebhookConfig, webhook_id) if webhook_id else None
        if webhook is None:
            error = "No escalation webhook is configured for this tenant."
        else:
            outcome = await service.escalate_ticket(tenant_db, ticket, webhook, actor_user_id=ctx.user.id)

    if next:
        return RedirectResponse(safe_relative_path(next, default="/tickets"), status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request, "tickets/_escalate_result.html", {"ticket": ticket, "outcome": outcome, "error": error}
    )


@router.post("/{ticket_id:int}/analyze/preview", response_class=HTMLResponse)
async def analyze_root_cause_preview(
    request: Request,
    ticket_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Computes rootcause.analyze() without posting it anywhere -- backs
    the "Analyze root cause" modal (base.html's #analyze-root-cause-
    modal, fetched by app.js's [data-analyze-root-cause] handler), opened
    from either the ticket detail page's own button or the tickets list
    row menu's same-named item. Posting the result as a comment is a
    separate, deliberate step from inside that modal (see
    analyze_root_cause below, unchanged)."""
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    analysis = await rootcause.analyze(tenant_db, ticket)
    return templates.TemplateResponse(
        request, "tickets/_root_cause_preview.html", {"ticket": ticket, "analysis": analysis}
    )


@router.post("/{ticket_id:int}/analyze")
async def analyze_root_cause(
    ticket_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """"Post as a comment" inside the analysis modal above -- always
    available on demand regardless of whether the tenant also opted into
    running this automatically at closure (Tickets > Platform Response
    Rules, rootcause.AUTO_ROOT_CAUSE_CONFIG_KEY). Recomputes the analysis
    itself rather than trusting anything the client echoes back from the
    preview above, so this always posts a fresh result."""
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        analysis = await rootcause.analyze(tenant_db, ticket)
        if analysis:
            await service.add_comment(tenant_db, ticket.id, author_user_id=None, body=analysis)
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


@router.post("/bulk-close")
async def bulk_close(
    ticket_ids: str = Form(...),
    next: str = Form("/tickets"),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """The list page's checkbox-select "Mass close" action -- same
    get_closed_status lookup and per-ticket service.update_status call as
    the single-ticket "Mark closed" quick action above uses for its own
    status, just looped over every checked id instead of one ticket_id
    path param. update_status is a no-op for a ticket already on that
    status (no duplicate log entry), and for a tenant with no is_closed-
    flagged status configured at all (closed_status is then None) the
    whole action is silently a no-op -- there's no sane status to invent
    in that case, same as "Mark closed" itself.

    Also drops a comment on every ticket closed this way (through the
    normal add_comment path, so it notifies watchers same as a human
    comment would) recording who reviewed it and that it was judged
    non-actionable -- a mass-close is exactly that judgment call, unlike
    the single-ticket "Mark closed" action, which carries no such
    assumption about *why* and so gets no comment of its own."""
    closed_status = await service.get_closed_status(tenant_db)
    if closed_status is not None:
        ids = [int(part) for part in ticket_ids.split(",") if part.strip().isdigit()]
        note = f"Seen by and acknowledged as non-actionable by {ctx.user.display_name} ({ctx.user.email})"
        for ticket_id in ids:
            ticket = await tenant_db.get(Ticket, ticket_id)
            if ticket is not None:
                await service.update_status(tenant_db, ticket, closed_status.key, changed_by_user_id=ctx.user.id)
                await service.add_comment(tenant_db, ticket.id, ctx.user.id, note)
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


# ------------------------------------------------------------- fields ----


@router.get("/fields", response_class=HTMLResponse)
async def fields_list(
    request: Request,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    stmt = (
        select(CustomField)
        .where(CustomField.scope == "ticket")
        .order_by(CustomField.sort_order, CustomField.label)
    )
    page_size = await get_tenant_config(tenant_db, "default_page_size")
    field_page = await paginate(tenant_db, stmt, page=page, page_size=page_size)
    return templates.TemplateResponse(
        request, "tickets/fields.html", {**nav, "ctx": ctx, "page": field_page, "error": None}
    )


@router.post("/fields")
async def create_field(
    field_key: str = Form(...),
    label: str = Form(...),
    field_type: str = Form("text"),
    select_options: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    # No asset_type_id (tickets don't have user-defined types -- see the
    # 0037 migration's docstring) and no is_required (see rain.modules.
    # tickets.schemas' note on why a required ticket-scoped field isn't
    # supported) -- both deliberate differences from the asset-scoped
    # twin of this route.
    options = [o.strip() for o in select_options.split(",") if o.strip()] if field_type == "select" else None
    tenant_db.add(
        CustomField(
            scope="ticket",
            asset_type_id=None,
            field_key=field_key.strip().lower(),
            label=label.strip(),
            field_type=field_type,
            select_options=options,
            is_required=False,
        )
    )
    await tenant_db.commit()
    return RedirectResponse("/tickets/fields", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/fields/{field_id:int}/delete")
async def delete_field(
    field_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    # scope == "ticket" guard -- see the asset-scoped twin of this route
    # (rain.modules.assets.router.delete_field) for why.
    field = await tenant_db.get(CustomField, field_id)
    if field is not None and field.scope == "ticket":
        await tenant_db.delete(field)
        await tenant_db.commit()
    return RedirectResponse("/tickets/fields", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/fields/import-pack", response_class=HTMLResponse)
async def field_pack_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    # require_admin, unlike the single-field CRUD just above (a
    # deliberate, previously-audited require_login quirk this doesn't
    # inherit) -- defining a whole pack of fields from an uploaded
    # spreadsheet in one shot is a tenant administration action, same
    # category as Asset Types/Service Catalog under Admin > Tenant
    # Administration, not a day-to-day ticketing task.
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "tickets/field_pack.html", {**nav, "ctx": ctx})


@router.post("/fields/import-pack/preview", response_class=HTMLResponse)
async def field_pack_preview(
    request: Request,
    file: UploadFile,
    fmt: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    raw = await file.read()
    guesses = sniff_columns(raw, fmt)
    existing_keys = {f.field_key for f in await service.ticket_fields(tenant_db)}

    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(
        request,
        "tickets/field_pack_preview.html",
        {**nav, "ctx": ctx, "guesses": guesses, "existing_keys": existing_keys},
    )


@router.post("/fields/import-pack/commit")
async def field_pack_commit(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    """Rows round-trip as plain indexed form fields (col_<i>_*) straight
    from the preview screen -- no import-stash token needed the way the
    row-data importers use, since there's no file left to re-read at this
    step: every value this needs (key/label/type/options, all already
    edited into the form) is right there in the POST body."""
    form = await request.form()
    existing_keys = {f.field_key for f in await service.ticket_fields(tenant_db)}
    seen_keys: set[str] = set()
    created = 0
    skipped: list[str] = []

    indices = sorted({int(k.split("_")[1]) for k in form.keys() if k.startswith("col_") and k.split("_")[1].isdigit()})
    for i in indices:
        if not form.get(f"col_{i}_include"):
            continue
        field_key = str(form.get(f"col_{i}_key", "")).strip().lower()
        label = str(form.get(f"col_{i}_label", "")).strip()
        field_type = str(form.get(f"col_{i}_type", "text")).strip()
        raw_options = str(form.get(f"col_{i}_options", ""))

        if not field_key or not label:
            skipped.append(f"column {i}: missing key or label")
            continue
        if not _FIELD_KEY_RE.match(field_key):
            skipped.append(f"'{field_key}': must start with a letter and contain only lowercase letters, digits, _")
            continue
        if field_key in existing_keys or field_key in seen_keys:
            skipped.append(f"'{field_key}': already exists")
            continue

        options = [o.strip() for o in raw_options.split(",") if o.strip()] if field_type == "select" else None
        tenant_db.add(
            CustomField(
                scope="ticket",
                asset_type_id=None,
                field_key=field_key,
                label=label,
                field_type=field_type,
                select_options=options,
                is_required=False,
            )
        )
        seen_keys.add(field_key)
        created += 1

    await tenant_db.commit()

    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(
        request, "tickets/field_pack_result.html", {**nav, "ctx": ctx, "created": created, "skipped": skipped}
    )


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
                await exporter.available_columns(tenant_db), selected_profile.columns if selected_profile else None
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
        columns = [{"source": s, "header": h} for s, h in await exporter.available_columns(tenant_db)]

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


# ------------------------------------------------------------- import ----


@router.get("/import", response_class=HTMLResponse)
async def import_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "tickets/import.html", {**nav, "ctx": ctx, "ticket_types": TICKET_TYPES})


@router.post("/import/preview", response_class=HTMLResponse)
async def import_preview(
    request: Request,
    file: UploadFile,
    fmt: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    raw = await file.read()
    token = secrets.token_hex(16)
    import_stash_path(token).write_bytes(raw)

    headers = importer.sniff_headers(raw, fmt)
    fields = await service.ticket_fields(tenant_db)
    targets = [
        ("ticket_type", "Type"),
        ("title", "Title"),
        ("description", "Description"),
        ("severity", "Severity"),
    ] + [(f"field_{f.id}", f.label) for f in fields]
    suggestions = {}
    for target_key, target_label in targets:
        match = next((h for h in headers if h.strip().lower() == target_label.strip().lower()), None)
        if match:
            suggestions[target_key] = match

    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(
        request,
        "tickets/import_preview.html",
        {
            **nav,
            "ctx": ctx,
            "token": token,
            "fmt": fmt,
            "headers": headers,
            "targets": targets,
            "suggestions": suggestions,
        },
    )


@router.post("/import/commit", response_class=HTMLResponse)
async def import_commit(
    request: Request,
    token: str = Form(...),
    fmt: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    mapping = {key[len("map_") :]: value for key, value in form.items() if key.startswith("map_") and value}

    try:
        stash = import_stash_path(token)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired import session -- start the import again.")
    if not stash.exists():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired import session -- start the import again.")
    raw = stash.read_bytes()
    rows = importer.parse_rows(raw, fmt)
    result = await importer.commit_import(tenant_db, rows=rows, mapping=mapping, actor_id=ctx.user.id)
    stash.unlink(missing_ok=True)

    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "tickets/import_result.html", {**nav, "ctx": ctx, "result": result})


# --------------------------------------------------------------- rules ---


class _NewRuleDefaults:
    """A lightweight stand-in for TicketRule, shaped just enough (same
    attribute names tickets/_promotion_type_fields.html reads) for the
    "New policy" modal to render from -- so that partial can be shared
    verbatim with rule_form.html's real TicketRule instead of needing
    two near-identical copies of the same tab/field markup kept in sync
    by hand. ml_algorithm/ml_sidecar_enabled/group_by/window_minutes/
    ml_score_threshold/ml_warmup_count are literally the same
    "recommended standard configuration" every newly created rule gets
    regardless of promotion_type (see _clamp_rule_ml_fields's own
    defaults) -- this is just that same set of defaults, reachable by
    attribute instead of by dict key, for a rule that doesn't exist
    yet."""

    def __init__(self, *, promotion_type: str = "single"):
        self.promotion_type = promotion_type
        self.ml_algorithm = DEFAULT_ML_ALGORITHM
        self.ml_sidecar_enabled = True
        self.group_by = "none"
        self.window_minutes = 5
        self.ml_score_threshold = 0.7
        self.ml_warmup_count = 250
        self.approval_flow_id = None


async def _clamp_rule_approval_flow_id(tenant_db: AsyncSession, approval_flow_id: str) -> int | None:
    """A rule's approval_flow_id (ticket_type == "change" only -- ignored
    otherwise) falls back to None the same light-touch way group_by/
    ml_algorithm/etc. do below rather than rejecting the whole save: a
    blank selection, or one naming a flow that's since been deleted,
    just means "file an unprotected change," not a validation error."""
    if not approval_flow_id:
        return None
    flow_id = int(approval_flow_id)
    return flow_id if await service.approval_flow_exists(tenant_db, flow_id) else None


def _clamp_rule_ml_fields(
    *, group_by: str, window_minutes: int, ml_score_threshold: float, ml_warmup_count: int, ml_algorithm: str
) -> dict:
    return dict(
        group_by=group_by if group_by in GROUP_BY_FIELDS else "none",
        window_minutes=max(1, window_minutes),
        # min(1.0, max(0.0, ...))/max(1, ...) so a typo/blank field can't
        # produce a threshold of 0 (every event would be "anomalous") or a
        # warmup of 0 (a rule fires on its very first, baseline-free event).
        ml_score_threshold=min(1.0, max(0.0, ml_score_threshold)),
        ml_warmup_count=max(1, ml_warmup_count),
        ml_algorithm=ml_algorithm if ml_algorithm in ML_ALGORITHMS else DEFAULT_ML_ALGORITHM,
    )


@router.get("/rules/all", response_class=HTMLResponse)
async def rules_list(
    request: Request,
    page: int = 1,
    prefill_pattern: str | None = None,
    prefill_match_field: str | None = None,
    prefill_ticket_type: str | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    stmt = select(TicketRule).order_by(TicketRule.sort_order)
    page_size = await get_tenant_config(tenant_db, "default_page_size")
    rule_page = await paginate(tenant_db, stmt, page=page, page_size=page_size)
    # "New policy from selection" (tickets/live's selection menu) lands
    # here with the New policy modal pre-filled from the selected
    # event(s) instead of asking the admin to retype a pattern they just
    # saw stream by -- see live.js's buildRulePrefillUrl. Defaults the
    # modal to the "repetition" tab (bundling repeat occurrences of the
    # same thing into one ticket is what that action is for), but every
    # field stays editable/switchable before saving.
    prefill = (
        {
            "pattern": prefill_pattern,
            "match_field": prefill_match_field if prefill_match_field in MATCH_FIELDS else "message",
            "ticket_type": prefill_ticket_type if prefill_ticket_type in TICKET_TYPES else "incident",
        }
        if prefill_pattern
        else None
    )
    approval_flows = await service.list_approval_flows(tenant_db)
    training_summaries = await bulk_rule_training_summary(tenant_db, rule_page.items)
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
            "group_by_fields": GROUP_BY_FIELDS,
            "ml_algorithms": [(k, label, desc) for k, (label, desc, _) in ML_ALGORITHMS.items()],
            "approval_flows": approval_flows,
            "training_summaries": training_summaries,
            "prefill": prefill,
            "rule": _NewRuleDefaults(promotion_type="repetition" if prefill else "single"),
            "tested_rule": None,
            "test_result": None,
        },
    )


@router.post("/rules/all")
async def rules_create(
    name: str = Form(...),
    promotion_type: str = Form("single"),
    ticket_type: str = Form(...),
    match_field: str = Form("message"),
    pattern: str = Form(...),
    title_template: str = Form("{message}"),
    severity: str = Form("medium"),
    asset_match_field: str = Form(""),
    sort_order: int = Form(0),
    group_by: str = Form("none"),
    window_minutes: int = Form(5),
    ml_score_threshold: float = Form(0.7),
    ml_warmup_count: int = Form(250),
    ml_algorithm: str = Form(DEFAULT_ML_ALGORITHM),
    ml_sidecar_enabled: bool = Form(False),
    approval_flow_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    if promotion_type not in PROMOTION_TYPES:
        promotion_type = "single"
    ml_fields = _clamp_rule_ml_fields(
        group_by=group_by,
        window_minutes=window_minutes,
        ml_score_threshold=ml_score_threshold,
        ml_warmup_count=ml_warmup_count,
        ml_algorithm=ml_algorithm,
    )
    tenant_db.add(
        TicketRule(
            name=name.strip(),
            promotion_type=promotion_type,
            ticket_type=ticket_type,
            match_field=match_field,
            pattern=pattern,
            title_template=title_template or "{message}",
            severity=severity,
            asset_match_field=asset_match_field or None,
            sort_order=sort_order,
            created_by=ctx.user.id,
            ml_sidecar_enabled=ml_sidecar_enabled if promotion_type == "repetition" else False,
            approval_flow_id=await _clamp_rule_approval_flow_id(tenant_db, approval_flow_id)
            if ticket_type == "change"
            else None,
            **ml_fields,
        )
    )
    await tenant_db.commit()
    return RedirectResponse("/tickets/rules/all", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/rules/{rule_id:int}/edit", response_class=HTMLResponse)
async def rules_edit_form(
    request: Request,
    rule_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    nav = await build_nav_context(ctx)
    rule = await tenant_db.get(TicketRule, rule_id)
    if rule is None:
        return RedirectResponse("/tickets/rules/all", status_code=status.HTTP_303_SEE_OTHER)
    approval_flows = await service.list_approval_flows(tenant_db)
    training_status = await rule_training_status(tenant_db, rule.id)
    return templates.TemplateResponse(
        request,
        "tickets/rule_form.html",
        {
            **nav,
            "ctx": ctx,
            "rule": rule,
            "ticket_types": TICKET_TYPES,
            "severities": SEVERITIES,
            "match_fields": MATCH_FIELDS,
            "group_by_fields": GROUP_BY_FIELDS,
            "ml_algorithms": [(k, label, desc) for k, (label, desc, _) in ML_ALGORITHMS.items()],
            "approval_flows": approval_flows,
            "training_status": training_status,
        },
    )


@router.post("/rules/{rule_id:int}/edit")
async def rules_edit(
    rule_id: int,
    name: str = Form(...),
    promotion_type: str = Form("single"),
    ticket_type: str = Form(...),
    match_field: str = Form("message"),
    pattern: str = Form(...),
    title_template: str = Form("{message}"),
    severity: str = Form("medium"),
    asset_match_field: str = Form(""),
    sort_order: int = Form(0),
    group_by: str = Form("none"),
    window_minutes: int = Form(5),
    ml_score_threshold: float = Form(0.7),
    ml_warmup_count: int = Form(250),
    ml_algorithm: str = Form(DEFAULT_ML_ALGORITHM),
    ml_sidecar_enabled: bool = Form(False),
    approval_flow_id: str = Form(""),
    is_active: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_admin),
):
    rule = await tenant_db.get(TicketRule, rule_id)
    if rule is not None:
        ml_fields = _clamp_rule_ml_fields(
            group_by=group_by,
            window_minutes=window_minutes,
            ml_score_threshold=ml_score_threshold,
            ml_warmup_count=ml_warmup_count,
            ml_algorithm=ml_algorithm,
        )
        rule.name = name.strip()
        rule.promotion_type = promotion_type if promotion_type in PROMOTION_TYPES else "single"
        rule.ticket_type = ticket_type
        rule.match_field = match_field
        rule.pattern = pattern
        rule.title_template = title_template or "{message}"
        rule.severity = severity
        rule.asset_match_field = asset_match_field or None
        rule.sort_order = sort_order
        rule.is_active = is_active
        rule.ml_sidecar_enabled = ml_sidecar_enabled if rule.promotion_type == "repetition" else False
        rule.approval_flow_id = (
            await _clamp_rule_approval_flow_id(tenant_db, approval_flow_id) if rule.ticket_type == "change" else None
        )
        for key, value in ml_fields.items():
            setattr(rule, key, value)
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

    tested_rule = await tenant_db.get(TicketRule, rule_id)
    matched = bool(tested_rule and re.search(tested_rule.pattern, sample))

    nav = await build_nav_context(ctx)
    stmt = select(TicketRule).order_by(TicketRule.sort_order)
    page_size = await get_tenant_config(tenant_db, "default_page_size")
    rule_page = await paginate(tenant_db, stmt, page=1, page_size=page_size)
    approval_flows = await service.list_approval_flows(tenant_db)
    training_summaries = await bulk_rule_training_summary(tenant_db, rule_page.items)
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
            "group_by_fields": GROUP_BY_FIELDS,
            "ml_algorithms": [(k, label, desc) for k, (label, desc, _) in ML_ALGORITHMS.items()],
            "approval_flows": approval_flows,
            "training_summaries": training_summaries,
            "prefill": None,
            "rule": _NewRuleDefaults(),
            "tested_rule": tested_rule,
            "test_result": {"rule_id": rule_id, "sample": sample, "matched": matched},
        },
    )


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
    page_size = await get_tenant_config(tenant_db, "default_page_size")
    rule_page = await paginate(tenant_db, stmt, page=page, page_size=page_size)
    auto_root_cause = await get_tenant_config(tenant_db, "auto_root_cause_on_close", False)
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
            "auto_root_cause": auto_root_cause,
        },
    )


@router.post("/platform-events/automation")
async def platform_events_automation(
    auto_root_cause_on_close: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_admin),
):
    """Saves rain.modules.tickets.rootcause's opt-in auto-analyze-at-
    closure flag for the active tenant. Off by default (see
    rain.core.tenant_config.DEFAULTS) -- the on-demand "Analyze root
    cause" button on a ticket works regardless of this setting. Lives
    here, not Admin > Ticket Statuses, since it's a reaction to a
    ticket event (closure) the same way every Platform Response Rule
    is, not a property of the statuses themselves."""
    await set_tenant_config(tenant_db, "auto_root_cause_on_close", auto_root_cause_on_close, updated_by=ctx.user.id)
    return RedirectResponse("/tickets/platform-events", status_code=status.HTTP_303_SEE_OTHER)


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
