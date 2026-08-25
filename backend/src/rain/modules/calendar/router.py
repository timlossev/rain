from __future__ import annotations

import calendar as pycalendar
import datetime as dt

from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from rain.core.config_store import config_store
from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.modules.calendar import ics, recurrence, service
from rain.modules.documents import service as document_service
from rain.web.nav import build_nav_context
from rain.web.safe_redirect import safe_relative_path
from rain.web.templating import templates

router = APIRouter(prefix="/calendar", tags=["Calendar"])


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
        # .date(): start_date/end_date now carry a time of day (a change's
        # window can start/end mid-day), but this grid places whole-day
        # chips, so only the day half matters for max()/min() against
        # grid_start/grid_end (both plain dates).
        day = max(change.start_date.date(), grid_start)
        last = min(change.end_date.date(), grid_end)
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


def _has_auto_refresh(entry) -> bool:
    policy = entry.policy_ref or {} if entry else {}
    return policy.get("type") == "refresh_document"


@router.get("/new", response_class=HTMLResponse)
async def new_entry_form(
    request: Request,
    date: str | None = None,
    document_id: int | None = None,
    redirect: str | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    documents = await document_service.list_documents(tenant_db)
    return templates.TemplateResponse(
        request,
        "calendar/form.html",
        {
            **nav,
            "ctx": ctx,
            "entry": None,
            "prefill_date": date or dt.date.today().isoformat(),
            "recurrence_presets": recurrence.RECURRENCE_PRESETS,
            "documents": documents,
            "selected_document_id": document_id,
            "auto_refresh": False,
            "redirect_to": safe_relative_path(redirect, default="/calendar"),
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
    document_id: str = Form(""),
    auto_refresh: bool = Form(False),
    redirect: str = Form("/calendar"),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc_id = int(document_id) if document_id else None
    await service.create_entry(
        tenant_db,
        title=title.strip(),
        description=description.strip() or None,
        start_date=dt.date.fromisoformat(start_date),
        recurrence=recurrence_key or None,
        recurrence_end=dt.date.fromisoformat(recurrence_end) if recurrence_end else None,
        emit_syslog_event=emit_syslog_event,
        event_program=event_program.strip() or None,
        document_id=doc_id,
        # auto_refresh only means anything alongside a chosen document --
        # a stray checked box with no document selected is a no-op, not
        # an error, same as the old refresh_document_id-alone field was.
        policy_ref={"type": "refresh_document", "document_id": doc_id} if (auto_refresh and doc_id) else None,
        created_by=ctx.user.id,
    )
    return RedirectResponse(safe_relative_path(redirect, default="/calendar"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{entry_id:int}/edit", response_class=HTMLResponse)
async def edit_entry_form(
    request: Request,
    entry_id: int,
    redirect: str | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    entry = await service.get_entry(tenant_db, entry_id)
    if entry is None:
        return RedirectResponse("/calendar", status_code=status.HTTP_303_SEE_OTHER)
    documents = await document_service.list_documents(tenant_db)
    return templates.TemplateResponse(
        request,
        "calendar/form.html",
        {
            **nav,
            "ctx": ctx,
            "entry": entry,
            "prefill_date": entry.start_date.isoformat(),
            "recurrence_presets": recurrence.RECURRENCE_PRESETS,
            "documents": documents,
            "selected_document_id": entry.document_id,
            "auto_refresh": _has_auto_refresh(entry),
            "redirect_to": safe_relative_path(redirect, default="/calendar"),
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
    document_id: str = Form(""),
    auto_refresh: bool = Form(False),
    redirect: str = Form("/calendar"),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    entry = await service.get_entry(tenant_db, entry_id)
    if entry is not None:
        doc_id = int(document_id) if document_id else None
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
            document_id=doc_id,
            policy_ref={"type": "refresh_document", "document_id": doc_id} if (auto_refresh and doc_id) else None,
        )
    return RedirectResponse(safe_relative_path(redirect, default="/calendar"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{entry_id:int}/delete")
async def delete_entry(
    entry_id: int,
    redirect: str = Form("/calendar"),
    tenant_db=Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    entry = await service.get_entry(tenant_db, entry_id)
    if entry is not None:
        await service.delete_entry(tenant_db, entry)
    return RedirectResponse(safe_relative_path(redirect, default="/calendar"), status_code=status.HTTP_303_SEE_OTHER)


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
