"""Service Catalog, client-facing: browse active items and submit one's
form, from inside the main app (Records Authority > Service Catalog). See
rain.modules.catalog.service for the shared logic this and rain.modules.
portal.router's own Catalog tab both call -- a submission behaves
identically regardless of which one it came through."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.modules.catalog import service
from rain.web.nav import build_nav_context
from rain.web.templating import templates

router = APIRouter(prefix="/catalog", tags=["Service Catalog"])


@router.get("", response_class=HTMLResponse)
async def catalog_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    items = await service.list_catalog_items(tenant_db, active_only=True)
    return templates.TemplateResponse(request, "catalog/list.html", {**nav, "ctx": ctx, "items": items})


@router.get("/{key}", response_class=HTMLResponse)
async def catalog_form(
    request: Request,
    key: str,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    item = await service.get_catalog_item_by_key(tenant_db, key)
    if item is None or not item.is_active:
        return RedirectResponse("/catalog", status_code=status.HTTP_303_SEE_OTHER)
    rendered = await service.render_fields(tenant_db, item)
    return templates.TemplateResponse(
        request,
        "catalog/form.html",
        {**nav, "ctx": ctx, "item": item, "rendered_fields": rendered, "submitted": {}, "errors": [], "back": "/catalog"},
    )


@router.post("/{key}")
async def catalog_submit(
    request: Request,
    key: str,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    item = await service.get_catalog_item_by_key(tenant_db, key)
    if item is None or not item.is_active:
        return RedirectResponse("/catalog", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    result = await service.submit_catalog_item(tenant_db, item, form, reporter_user_id=ctx.user.id)
    if result.errors:
        rendered = await service.render_fields(tenant_db, item)
        submitted = {f.field_key: form.get(f"answer_{f.field_key}", "") for f in item.fields}
        return templates.TemplateResponse(
            request,
            "catalog/form.html",
            {
                **nav,
                "ctx": ctx,
                "item": item,
                "rendered_fields": rendered,
                "submitted": submitted,
                "errors": result.errors,
                "back": "/catalog",
            },
        )
    return RedirectResponse(f"/tickets/{result.ticket.ticket_number}", status_code=status.HTTP_303_SEE_OTHER)
