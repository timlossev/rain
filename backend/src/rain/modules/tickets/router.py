from __future__ import annotations

import io

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.crypto import encrypt_json
from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.db.tenant_models import NotificationChannel, Ticket, TicketRule
from rain.modules.assets import service as asset_service
from rain.modules.documents import service as document_service
from rain.modules.tickets import exporter, service
from rain.modules.tickets.schemas import CHANNEL_TYPES, MATCH_FIELDS, SEVERITIES, TICKET_STATUSES, TICKET_TYPES
from rain.web.nav import build_nav_context
from rain.web.templating import templates

router = APIRouter(prefix="/tickets")


# ------------------------------------------------------------- tickets ---


@router.get("", response_class=HTMLResponse)
async def list_tickets(
    request: Request,
    ticket_type: str | None = None,
    ticket_status: str | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    tickets = await service.list_tickets(tenant_db, ticket_type=ticket_type, status=ticket_status)
    return templates.TemplateResponse(
        request,
        "tickets/list.html",
        {
            **nav,
            "ctx": ctx,
            "tickets": tickets,
            "ticket_types": TICKET_TYPES,
            "statuses": TICKET_STATUSES,
            "selected_type": ticket_type,
            "selected_status": ticket_status,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_ticket_form(
    request: Request,
    ticket_type: str = "incident",
    source_event_id: int | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    event = await service.get_event(tenant_db, source_event_id) if source_event_id else None
    assets = await asset_service.list_assets(tenant_db)

    prefill_title = f"{event.program or event.host or 'Event'}: {event.message[:120]}" if event else ""
    prefill_description = event.message if event else ""
    suggested_asset_id = None
    if event is not None and event.host:
        for asset in assets:
            if asset.external_id == event.host:
                suggested_asset_id = asset.id
                break

    return templates.TemplateResponse(
        request,
        "tickets/form.html",
        {
            **nav,
            "ctx": ctx,
            "ticket_types": TICKET_TYPES,
            "severities": SEVERITIES,
            "assets": assets,
            "selected_type": ticket_type,
            "source_event_id": source_event_id,
            "prefill_title": prefill_title,
            "prefill_description": prefill_description,
            "suggested_asset_id": suggested_asset_id,
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
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    from rain.modules.tickets.notifications import notify_ticket_created

    ticket = await service.create_ticket(
        tenant_db,
        ticket_type=ticket_type,
        title=title.strip(),
        description=description.strip() or None,
        severity=severity,
        asset_id=int(asset_id) if asset_id else None,
        source_event_id=int(source_event_id) if source_event_id else None,
        reporter_user_id=ctx.user.id,
    )
    await notify_ticket_created(tenant_db, ticket)
    return RedirectResponse(f"/tickets/{ticket.id}", status_code=status.HTTP_303_SEE_OTHER)


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
    return templates.TemplateResponse(
        request,
        "tickets/detail.html",
        {**nav, "ctx": ctx, "ticket": ticket, "statuses": TICKET_STATUSES, "document_links": document_links},
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
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    ticket = await tenant_db.get(Ticket, ticket_id)
    if ticket is not None:
        await service.update_status(tenant_db, ticket, new_status)
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


# ------------------------------------------------------------- export ----


@router.get("/export/run", response_class=HTMLResponse)
async def export_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(
        request, "tickets/export.html", {**nav, "ctx": ctx, "ticket_types": TICKET_TYPES, "statuses": TICKET_STATUSES}
    )


@router.post("/export/run")
async def export_run(
    ticket_type: str = Form(""),
    ticket_status: str = Form(""),
    fmt: str = Form("csv"),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    rows = await exporter.build_rows(tenant_db, ticket_type=ticket_type or None, status=ticket_status or None)
    if fmt == "json":
        content, media_type, filename = exporter.render_json(rows), "application/json", "tickets-export.json"
    else:
        content, media_type, filename = exporter.render_csv(rows), "text/csv", "tickets-export.csv"
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------- rules ---


@router.get("/rules/all", response_class=HTMLResponse)
async def rules_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    result = await tenant_db.execute(select(TicketRule).order_by(TicketRule.sort_order))
    rule_rows = list(result.scalars())
    return templates.TemplateResponse(
        request,
        "tickets/rules.html",
        {
            **nav,
            "ctx": ctx,
            "rules": rule_rows,
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
    result = await tenant_db.execute(select(TicketRule).order_by(TicketRule.sort_order))
    rule_rows = list(result.scalars())
    return templates.TemplateResponse(
        request,
        "tickets/rules.html",
        {
            **nav,
            "ctx": ctx,
            "rules": rule_rows,
            "ticket_types": TICKET_TYPES,
            "severities": SEVERITIES,
            "match_fields": MATCH_FIELDS,
            "test_result": {"rule_id": rule_id, "sample": sample, "matched": matched},
        },
    )


# --------------------------------------------------------- notifications -


@router.get("/notifications/all", response_class=HTMLResponse)
async def notifications_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    result = await tenant_db.execute(select(NotificationChannel).order_by(NotificationChannel.name))
    channels = list(result.scalars())
    return templates.TemplateResponse(
        request,
        "tickets/notifications.html",
        {**nav, "ctx": ctx, "channels": channels, "channel_types": CHANNEL_TYPES},
    )


@router.post("/notifications/all")
async def notifications_create(
    request: Request,
    channel_type: str = Form(...),
    name: str = Form(...),
    notify_on_incident: bool = Form(False),
    notify_on_vulnerability: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    if channel_type == "email":
        recipients = [addr.strip() for addr in str(form.get("recipients", "")).split(",") if addr.strip()]
        config = {"recipients": recipients}
    else:
        config = {"webhook_url": str(form.get("webhook_url", "")).strip()}

    tenant_db.add(
        NotificationChannel(
            channel_type=channel_type,
            name=name.strip(),
            config_encrypted=encrypt_json(config),
            notify_on_incident=notify_on_incident,
            notify_on_vulnerability=notify_on_vulnerability,
        )
    )
    await tenant_db.commit()
    return RedirectResponse("/tickets/notifications/all", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notifications/{channel_id:int}/delete")
async def notifications_delete(
    channel_id: int, tenant_db: AsyncSession = Depends(get_tenant_db), _: CurrentUser = Depends(require_login)
):
    channel = await tenant_db.get(NotificationChannel, channel_id)
    if channel is not None:
        await tenant_db.delete(channel)
        await tenant_db.commit()
    return RedirectResponse("/tickets/notifications/all", status_code=status.HTTP_303_SEE_OTHER)
