"""Global search across Tickets and Documents. Typing a ticket/document
number (INC-000001, DOC-000004, ...) jumps straight to that record
instead of showing a results page that could only ever contain it; any
other query runs rain.modules.search.service.search (Postgres full-text,
see that module's docstring for why not vector/semantic search)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.modules.search import service
from rain.web.nav import build_nav_context
from rain.web.templating import templates

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = "",
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    q = q.strip()
    if q:
        direct = await service.find_by_number(tenant_db, q)
        if direct is not None:
            return RedirectResponse(direct.href, status_code=status.HTTP_303_SEE_OTHER)

    nav = await build_nav_context(ctx)
    results = await service.search(tenant_db, q) if q else []
    return templates.TemplateResponse(
        request,
        "search/results.html",
        {**nav, "ctx": ctx, "q": q, "results": results},
    )
