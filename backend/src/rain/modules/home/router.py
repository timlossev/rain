"""The landing page: `GET /home`, and what `GET /` redirects a signed-in
user to (rain.main's own `index` route) instead of straight into
Records Authority -- a neutral first screen rather than assuming
tickets are what everyone wants to see first.

Shows every document flagged "Show on landing page" (Document.
show_on_landing_page, set from the document's own page -- see
rain.modules.documents.router), rendered the same way its own Contents
tab/PDF export would (Markdown through the same sanitizing renderer,
plain text as-is). Falls back to a plain "Welcome to <instance>" (the
template's own default, not rendered here) when none are flagged."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.modules.documents import service as document_service
from rain.modules.documents import storage as document_storage
from rain.modules.documents import textbody
from rain.web.nav import build_nav_context
from rain.web.templating import templates

router = APIRouter(tags=["Home"])


@router.get("/home", response_class=HTMLResponse)
async def home(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    flagged = await document_service.list_landing_page_documents(tenant_db)

    landing_docs = []
    for doc in flagged:
        kind = textbody.body_kind(doc.filename)
        if kind is None:
            continue  # e.g. a PDF/image flagged with nothing inline to render -- silently skipped, not an error
        try:
            text = textbody.decode_body(document_storage.get_storage().read(doc.storage_key))
        except FileNotFoundError:
            continue
        landing_docs.append(
            {
                "doc": doc,
                "html": textbody.render_markdown(text) if kind == "markdown" else None,
                "text": text if kind == "text" else None,
            }
        )

    return templates.TemplateResponse(
        request,
        "home/index.html",
        {**nav, "ctx": ctx, "landing_docs": landing_docs},
    )
