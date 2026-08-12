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
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from rain.core.rbac import require_login
from rain.core.security import SESSION_COOKIE_NAME
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, resolve_ws_tenant_schema
from rain.db.base import tenant_session
from rain.modules.tickets import service
from rain.modules.tickets.live_bus import asyncpg_dsn, channel_for
from rain.modules.tickets.syslog_parser import severity_label
from rain.web.nav import build_nav_context
from rain.web.templating import templates

logger = logging.getLogger("rain.live")

router = APIRouter(prefix="/tickets")


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
