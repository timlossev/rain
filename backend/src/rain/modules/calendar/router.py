from __future__ import annotations

import calendar as pycalendar
import datetime as dt

from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from rain.core.config_store import config_store
from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.modules.calendar import ics, recurrence, service
from rain.web.nav import build_nav_context
from rain.web.templating import templates

router = APIRouter(prefix="/calendar")


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    start = dt.date(year, month, 1)
    end = dt.date(year, month, pycalendar.monthrange(year, month)[1])
    return start, end


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


@router.get("", response_class=HTMLResponse)
async def month_view(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    today = dt.date.today()
    year = year or today.year
    month = month or today.month
    month = max(1, min(12, month))

    month_start, month_end = _month_bounds(year, month)
    weeks = pycalendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    grid_start, grid_end = weeks[0][0], weeks[-1][-1]

    entries = await service.list_entries(tenant_db, active_only=True)
    by_date: dict[dt.date, list] = {}
    for entry in entries:
        for occ in recurrence.occurrences_in_range(entry, grid_start, grid_end):
            by_date.setdefault(occ, []).append(entry)

    # Change tickets with a start/end window overlapping the visible grid --
    # shown alongside CalendarEntry occurrences, one chip per day in range,
    # so a change's maintenance window is visible without opening the ticket.
    changes = await service.list_changes_in_range(tenant_db, grid_start, grid_end)
    changes_by_date: dict[dt.date, list] = {}
    for change in changes:
        day = max(change.start_date, grid_start)
        last = min(change.end_date, grid_end)
        while day <= last:
            changes_by_date.setdefault(day, []).append(change)
            day += dt.timedelta(days=1)

    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)

    return templates.TemplateResponse(
        request,
        "calendar/month.html",
        {
            **nav,
            "ctx": ctx,
            "year": year,
            "month": month,
            "month_name": dt.date(year, month, 1).strftime("%B %Y"),
            "weeks": weeks,
            "by_date": by_date,
            "changes_by_date": changes_by_date,
            "today": today,
            "month_start": month_start,
            "month_end": month_end,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_entry_form(
    request: Request,
    date: str | None = None,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(
        request,
        "calendar/form.html",
        {
            **nav,
            "ctx": ctx,
            "entry": None,
            "prefill_date": date or dt.date.today().isoformat(),
            "recurrence_presets": recurrence.RECURRENCE_PRESETS,
            "error": None,
        },
    )


@router.post("")
async def create_entry(
    title: str = Form(...),
    description: str = Form(""),
    start_date: str = Form(...),
    recurrence_key: str = Form("", alias="recurrence"),
    recurrence_end: str = Form(""),
    emit_syslog_event: bool = Form(False),
    event_program: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    await service.create_entry(
        tenant_db,
        title=title.strip(),
        description=description.strip() or None,
        start_date=dt.date.fromisoformat(start_date),
        recurrence=recurrence_key or None,
        recurrence_end=dt.date.fromisoformat(recurrence_end) if recurrence_end else None,
        emit_syslog_event=emit_syslog_event,
        event_program=event_program.strip() or None,
        created_by=ctx.user.id,
    )
    return RedirectResponse("/calendar", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{entry_id:int}/edit", response_class=HTMLResponse)
async def edit_entry_form(
    request: Request,
    entry_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    entry = await service.get_entry(tenant_db, entry_id)
    if entry is None:
        return RedirectResponse("/calendar", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "calendar/form.html",
        {
            **nav,
            "ctx": ctx,
            "entry": entry,
            "prefill_date": entry.start_date.isoformat(),
            "recurrence_presets": recurrence.RECURRENCE_PRESETS,
            "error": None,
        },
    )


@router.post("/{entry_id:int}")
async def update_entry(
    entry_id: int,
    title: str = Form(...),
    description: str = Form(""),
    start_date: str = Form(...),
    recurrence_key: str = Form("", alias="recurrence"),
    recurrence_end: str = Form(""),
    is_active: bool = Form(False),
    emit_syslog_event: bool = Form(False),
    event_program: str = Form(""),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    entry = await service.get_entry(tenant_db, entry_id)
    if entry is not None:
        await service.update_entry(
            tenant_db,
            entry,
            title=title.strip(),
            description=description.strip() or None,
            start_date=dt.date.fromisoformat(start_date),
            recurrence=recurrence_key or None,
            recurrence_end=dt.date.fromisoformat(recurrence_end) if recurrence_end else None,
            is_active=is_active,
            emit_syslog_event=emit_syslog_event,
            event_program=event_program.strip() or None,
        )
    return RedirectResponse("/calendar", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{entry_id:int}/delete")
async def delete_entry(
    entry_id: int,
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    entry = await service.get_entry(tenant_db, entry_id)
    if entry is not None:
        await service.delete_entry(tenant_db, entry)
    return RedirectResponse("/calendar", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/export")
async def export_calendar(
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    entries = await service.list_entries(tenant_db)
    body = ics.export_ics(entries, instance_name=config_store.get("instance_name") or "RAIN")
    return Response(
        body,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="rain-calendar.ics"'},
    )


@router.get("/import", response_class=HTMLResponse)
async def import_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "calendar/import.html", {**nav, "ctx": ctx, "error": None, "imported": None})


@router.post("/import", response_class=HTMLResponse)
async def import_run(
    request: Request,
    file: UploadFile,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    raw = (await file.read()).decode("utf-8", errors="replace")
    parsed = ics.parse_ics(raw)
    for fields in parsed:
        await service.create_entry(tenant_db, created_by=ctx.user.id, **fields)
    return templates.TemplateResponse(
        request, "calendar/import.html", {**nav, "ctx": ctx, "error": None, "imported": len(parsed)}
    )
