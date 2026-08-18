"""The real-time syslog viewer: an HTML page plus its WebSocket feed.

The WebSocket route can't use FastAPI's normal Depends(get_current_user)
chain (that's typed against Request, not WebSocket -- see the docstring on
rain.core.tenancy._load_session_and_user), so auth here is resolved
manually via resolve_ws_tenant_schema before the handshake is even
accepted: an invalid/missing session closes the socket with 4401 rather
than completing the upgrade.
"""
from __future__ import annotations

import asyncio
import json
import logging

import asyncpg
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket, WebSocketDisconnect

from rain.core.rbac import require_internal_admin, require_login
from rain.core.security import SESSION_COOKIE_NAME
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db, resolve_ws_tenant_schema
from rain.db.base import control_session, tenant_session
from rain.db.control_models import SyslogSourceMap
from rain.modules.tickets import service
from rain.modules.tickets.live_bus import asyncpg_dsn, channel_for
from rain.modules.tickets.syslog_parser import severity_label
from rain.web.nav import build_nav_context
from rain.web.templating import templates

logger = logging.getLogger("rain.live")

router = APIRouter(prefix="/tickets", tags=["Tickets"])


def _event_payload(event) -> str:
    return json.dumps(
        {
            "id": event.id,
            "received_at": event.received_at.isoformat(),
            "host": event.host,
            "program": event.program,
            "severity": event.severity,
            "severity_label": severity_label(event.severity),
            "message": event.message[:500],
            "event_format": event.event_format,
        }
    )


@router.get("/live", response_class=HTMLResponse)
async def live_page(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "tickets/live.html", {**nav, "ctx": ctx})


@router.post("/live/bulk-promote")
async def live_bulk_promote(
    event_ids: str = Form(...),  # comma-separated ids, built client-side from the checked rows
    ticket_type: str = Form(...),  # incident | vulnerability
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Backs the live-feed selection menu's "Turn these into incidents/
    vulnerabilities" -- one ticket per selected event (there's no "one
    ticket, several source events" shape in the schema), titled/described
    the same way the single-event New Ticket form prefills from
    source_event_id. Skips the review step that flow gets -- deliberately,
    since reviewing N tickets one at a time defeats the point of a bulk
    action; assignee/description edits happen after, on each ticket."""
    if ticket_type not in ("incident", "vulnerability"):
        return RedirectResponse("/tickets/live", status_code=status.HTTP_303_SEE_OTHER)
    ids = [int(i) for i in event_ids.split(",") if i.strip().isdigit()]
    for event_id in ids:
        event = await service.get_event(tenant_db, event_id)
        if event is None:
            continue
        title = f"{event.program or event.host or 'Event'}: {event.message[:120]}"
        await service.create_ticket(
            tenant_db,
            ticket_type=ticket_type,
            title=title,
            description=event.message,
            source_event_id=event.id,
            reporter_user_id=ctx.user.id,
        )
    return RedirectResponse(f"/tickets?ticket_type={ticket_type}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/live/bulk-discard")
async def live_bulk_discard(
    hosts: str = Form(...),  # comma-separated distinct hosts, deduped client-side from the selection
    _: CurrentUser = Depends(require_internal_admin),
):
    """Backs the live-feed selection menu's "Discard these" -- one
    negation rule (Admin > Syslog Listener) per distinct host among the
    selected events. Admin-only (unlike bulk-promote above): this writes
    control-schema routing config that affects every future event from
    that host, not just tenant-local ticket data. Doesn't touch the
    already-persisted events themselves -- only stops the host's *future*
    events from reaching a tenant at all."""
    host_list = sorted({h.strip() for h in hosts.split(",") if h.strip()})
    if host_list:
        async with control_session() as session:
            for host in host_list:
                session.add(SyslogSourceMap(match_field="host", pattern=host, is_regex=False, action="discard"))
            await session.commit()
    return RedirectResponse("/admin/syslog-sources", status_code=status.HTTP_303_SEE_OTHER)


@router.websocket("/live/ws")
async def live_ws(websocket: WebSocket) -> None:
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    resolved = await resolve_ws_tenant_schema(token)
    if resolved is None:
        await websocket.close(code=4401)
        return
    _user, schema_name = resolved

    await websocket.accept()

    async with tenant_session(schema_name) as db:
        for event in await service.recent_events(db, limit=50):
            await websocket.send_text(_event_payload(event))

    queue: asyncio.Queue[str] = asyncio.Queue()
    listen_conn = await asyncpg.connect(dsn=asyncpg_dsn())

    async def _on_notify(_conn, _pid, _channel, payload: str) -> None:
        queue.put_nowait(payload)

    await listen_conn.add_listener(channel_for(schema_name), _on_notify)

    async def _forward() -> None:
        while True:
            payload = await queue.get()
            await websocket.send_text(payload)

    async def _watch_disconnect() -> None:
        while True:
            await websocket.receive_text()  # the client never sends anything; this just detects a close

    forward_task = asyncio.create_task(_forward())
    watch_task = asyncio.create_task(_watch_disconnect())
    try:
        await asyncio.wait({forward_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        watch_task.cancel()
        await listen_conn.close()
