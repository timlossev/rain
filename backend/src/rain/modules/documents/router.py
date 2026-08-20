from __future__ import annotations

import io
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.convertors import Convertor, register_url_convertor

from rain.core.pagination import paginate
from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.modules.assets import service as asset_service
from rain.modules.documents import service, storage, textbody
from rain.modules.documents.schemas import LINKED_TYPES, MAX_UPLOAD_BYTES
from rain.modules.tickets import service as ticket_service
from rain.modules.webhooks import service as webhook_service
from rain.web.nav import build_nav_context
from rain.web.pdf import render_pdf
from rain.web.templating import templates


class _DocRefConvertor(Convertor):
    """Matches a doc_number ("DOC-000123" -- the URL scheme document
    detail links use) or, for back-compat with any link/bookmark built
    before that switch, a bare integer id. See rain.modules.tickets.
    router's _TicketRefConvertor for why this is a real regex-constrained
    converter rather than a plain {doc_ref} str."""

    regex = r"DOC-\d+|\d+"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


register_url_convertor("doc_ref", _DocRefConvertor())

router = APIRouter(prefix="/documents", tags=["Documents"])


def _filename_slug(title: str) -> str:
    """Turns a document's title into a storage filename stem for the
    "type new content" create path -- there's no real uploaded filename
    to fall back on there. Not a uniqueness guarantee (storage_key
    already carries a random prefix, see storage.make_storage_key); this
    is purely cosmetic, for what the download filename looks like."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip()).strip("-").lower()
    return slug or "document"


async def _log_ticket_link_activity(
    tenant_db: AsyncSession, *, linked: bool, document, ticket_id: int, user_id: int | None
) -> None:
    """Document links are polymorphic (ticket or asset -- LINKED_TYPES),
    but only tickets have an activity feed to log to; assets don't. Kept
    here rather than in documents/service.py so that module doesn't need
    to import rain.modules.tickets (which already imports documents/
    service.py the other way, for attach_document actions). Uses the
    generic field-change log (Date - Actor - action, one line) rather
    than a comment -- a link/unlink is a system event, not something a
    person said."""
    label = f"{document.doc_number}: {document.title}"
    await ticket_service.log_field_change(
        tenant_db,
        ticket_id,
        "document",
        None if linked else label,
        label if linked else None,
        changed_by_user_id=user_id,
    )


@router.get("", response_class=HTMLResponse)
async def list_documents(
    request: Request,
    search: str | None = None,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    doc_page = await paginate(tenant_db, service.document_list_stmt(search=search), page=page)
    return templates.TemplateResponse(
        request, "documents/list.html", {**nav, "ctx": ctx, "page": doc_page, "search": search or ""}
    )


@router.get("/new", response_class=HTMLResponse)
async def new_document_form(
    request: Request,
    linked_type: str = "",
    linked_id: int | None = None,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(
        request, "documents/form.html", {**nav, "ctx": ctx, "linked_type": linked_type, "linked_id": linked_id, "error": None}
    )


@router.post("")
async def create_document(
    request: Request,
    file: UploadFile | None = None,
    title: str = Form(...),
    description: str = Form(""),
    body: str = Form(""),
    body_format: str = Form("txt"),
    linked_type: str = Form(""),
    linked_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    # Two mutually exclusive ways in: an uploaded file, or typed-in
    # content saved as a new .txt/.md placeholder named after the title
    # (editable further, or wired to a webhook for auto-update, from the
    # document's own page afterward) -- no need to have a real file on
    # hand just to create a document.
    has_file = file is not None and file.filename
    if has_file:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            nav = await build_nav_context(ctx)
            return templates.TemplateResponse(
                request,
                "documents/form.html",
                {**nav, "ctx": ctx, "linked_type": linked_type, "linked_id": linked_id, "error": "File too large (max 25MB)."},
                status_code=400,
            )
        filename = file.filename or "file"
        mime_type = file.content_type
    elif body.strip():
        ext = "md" if body_format == "md" else "txt"
        filename = f"{_filename_slug(title)}.{ext}"
        mime_type = "text/markdown" if ext == "md" else "text/plain"
        data = body.encode("utf-8")
    else:
        nav = await build_nav_context(ctx)
        return templates.TemplateResponse(
            request,
            "documents/form.html",
            {**nav, "ctx": ctx, "linked_type": linked_type, "linked_id": linked_id, "error": "Upload a file, or type some content."},
            status_code=400,
        )

    key = storage.make_storage_key(ctx.active_tenant.schema_name, filename)
    storage.get_storage().save(key, data)

    doc = await service.create_document(
        tenant_db,
        title=title.strip(),
        description=description.strip() or None,
        filename=filename,
        storage_key=key,
        mime_type=mime_type,
        size_bytes=len(data),
        uploaded_by=ctx.user.id,
    )

    if linked_type in LINKED_TYPES and linked_id:
        await service.add_link(tenant_db, doc.id, linked_type, int(linked_id), ctx.user.id)
        if linked_type == "asset":
            return RedirectResponse(f"/assets/{linked_id}/edit", status_code=status.HTTP_303_SEE_OTHER)
        await _log_ticket_link_activity(tenant_db, linked=True, document=doc, ticket_id=int(linked_id), user_id=ctx.user.id)
        return RedirectResponse(f"/tickets/{linked_id}", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse(f"/documents/{doc.doc_number}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{doc_ref:doc_ref}", response_class=HTMLResponse)
async def document_detail(
    request: Request,
    doc_ref: str,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    doc = await service.get_document_by_ref(tenant_db, doc_ref)
    if doc is None:
        return RedirectResponse("/documents", status_code=status.HTTP_303_SEE_OTHER)
    body_kind = textbody.body_kind(doc.filename)
    body_text = None
    if body_kind is not None:
        try:
            body_text = textbody.decode_body(storage.get_storage().read(doc.storage_key))
        except FileNotFoundError:
            body_kind = None
    webhooks = await webhook_service.list_webhooks(tenant_db) if body_kind is not None else []
    # So the Links tab can show "INC-000123"/"CI-000123" instead of a bare
    # database id for ticket-/asset-typed links -- DocumentLink is
    # polymorphic and doesn't eager-load a Ticket or Asset, so these are
    # small bulk lookups rather than widening the model.
    ticket_link_ids = [link.linked_id for link in doc.links if link.linked_type == "ticket"]
    ticket_numbers = await ticket_service.get_ticket_numbers(tenant_db, ticket_link_ids)
    asset_link_ids = [link.linked_id for link in doc.links if link.linked_type == "asset"]
    asset_numbers = await asset_service.get_ci_numbers(tenant_db, asset_link_ids)
    return templates.TemplateResponse(
        request,
        "documents/detail.html",
        {
            **nav,
            "ctx": ctx,
            "doc": doc,
            "linked_types": LINKED_TYPES,
            "body_kind": body_kind,
            "body_text": body_text,
            "webhooks": webhooks,
            "ticket_numbers": ticket_numbers,
            "asset_numbers": asset_numbers,
        },
    )


@router.post("/{document_id:int}/description")
async def update_document_description(
    document_id: int,
    description: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is not None:
        await service.update_description(tenant_db, doc, description.strip() or None)
    return RedirectResponse(f"/documents/{doc.doc_number if doc else document_id}?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{document_id:int}/body")
async def update_document_body(
    document_id: int,
    body: str = Form(...),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if textbody.body_kind(doc.filename) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This document type isn't inline-editable.")
    # Diffs against the stored content itself (see service.update_body) --
    # opening the editor and saving with no real edits doesn't fire the
    # alert_on_change SyslogEvent that a genuine content change does.
    await service.update_body(tenant_db, doc, body)
    return RedirectResponse(f"/documents/{doc.doc_number}?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{document_id:int}/webhook-config")
async def set_document_webhook_config(
    document_id: int,
    webhook_id: str = Form(""),
    alert_on_change: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is not None:
        await service.update_webhook_config(
            tenant_db, doc, webhook_id=int(webhook_id) if webhook_id else None, alert_on_change=alert_on_change
        )
    return RedirectResponse(f"/documents/{doc.doc_number if doc else document_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{document_id:int}/refresh-from-webhook")
async def refresh_document_from_webhook(
    document_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """The manual "Refresh from webhook" button -- rain.modules.documents.
    service.refresh_from_webhook does the actual call/diff/save/alert
    work (also used by a calendar entry's "refresh this document on
    occurrence" policy, rain.modules.calendar.sweep); this route just
    turns its outcome into a redirect + flash."""
    doc = await service.get_document(tenant_db, document_id)
    if doc is None:
        return RedirectResponse(f"/documents/{document_id}", status_code=status.HTTP_303_SEE_OTHER)

    outcome = await service.refresh_from_webhook(tenant_db, doc)
    if not outcome.ok:
        return RedirectResponse(
            f"/documents/{doc.doc_number}?error={quote(f'Webhook refresh failed: {outcome.error}')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    query = "refreshed=1" if outcome.changed else "refreshed=0"
    return RedirectResponse(f"/documents/{doc.doc_number}?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{document_id:int}/preview-markdown", response_class=HTMLResponse)
async def preview_markdown(document_id: int, body: str = Form(...), _: CurrentUser = Depends(require_login)):
    return HTMLResponse(textbody.render_markdown(body))


@router.get("/{document_id:int}/body-preview", response_class=HTMLResponse)
async def body_preview(
    document_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Rendered-body fragment for the "View" modal on linked-document
    lists (ticket/asset detail) -- same renderer as the inline editor's
    Preview tab and the PDF export, so all three agree."""
    doc = await service.get_document(tenant_db, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    kind = textbody.body_kind(doc.filename)
    if kind is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This document type has no inline preview.")
    try:
        text = textbody.decode_body(storage.get_storage().read(doc.storage_key))
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file is missing.")
    if kind == "markdown":
        return HTMLResponse(textbody.render_markdown(text))
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(f"<pre class=\"doc-preview-text\">{escaped}</pre>")


@router.get("/{document_id:int}/pdf")
async def document_pdf(
    document_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is None:
        return RedirectResponse("/documents", status_code=status.HTTP_303_SEE_OTHER)

    body_kind = textbody.body_kind(doc.filename)
    body_text = None
    body_html = None
    if body_kind is not None:
        try:
            text = textbody.decode_body(storage.get_storage().read(doc.storage_key))
            if body_kind == "markdown":
                body_html = textbody.render_markdown(text)
            else:
                body_text = text
        except FileNotFoundError:
            body_kind = None

    pdf_bytes = render_pdf(
        "pdf/document.html",
        {
            "doc": doc,
            "doc_kind": "Document",
            "body_kind": body_kind,
            "body_text": body_text,
            "body_html": body_html,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    )
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{doc.doc_number}.pdf"'},
    )


@router.get("/{document_id:int}/download")
async def download_document(
    document_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = storage.get_storage().read(doc.storage_key)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=doc.mime_type or "application/octet-stream",
        # attachment (not inline) so the browser never renders an
        # untrusted upload in the page's origin, regardless of mime_type.
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.post("/{document_id:int}/delete")
async def delete_document(
    document_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is not None:
        storage.get_storage().delete(doc.storage_key)
        await service.delete_document(tenant_db, doc)
    return RedirectResponse("/documents", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/search")
async def search_documents(
    q: str = "",
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Backs the "Link existing" picker (documents/_links_fragment.html)
    -- same predictive-search shape as tickets' assignee/asset pickers."""
    q = q.strip()
    if len(q) < 2:
        return []
    docs = await service.list_documents(tenant_db, search=q)
    return [{"id": d.id, "label": f"{d.doc_number}: {d.title}"} for d in docs[:8]]


@router.post("/link")
async def link_existing_document(
    document_id: int = Form(...),
    linked_type: str = Form(...),
    linked_id: int = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """The other direction from link_document below -- that one starts
    from a document's own page and picks a ticket/asset to attach it to;
    this one starts from the ticket/asset page (_links_fragment.html's
    "Link existing") and picks a document, so it returns to that page
    instead of the document's."""
    if linked_type in LINKED_TYPES:
        await service.add_link(tenant_db, document_id, linked_type, linked_id, ctx.user.id)
        if linked_type == "ticket":
            doc = await service.get_document(tenant_db, document_id)
            if doc is not None:
                await _log_ticket_link_activity(tenant_db, linked=True, document=doc, ticket_id=linked_id, user_id=ctx.user.id)
    if linked_type == "asset":
        asset = await asset_service.get_asset(tenant_db, linked_id)
        return RedirectResponse(
            f"/assets/{asset.ci_number if asset else linked_id}/edit", status_code=status.HTTP_303_SEE_OTHER
        )
    ticket = await ticket_service.get_ticket(tenant_db, linked_id)
    return RedirectResponse(
        f"/tickets/{ticket.ticket_number if ticket else linked_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/{document_id:int}/link")
async def link_document(
    document_id: int,
    linked_type: str = Form(...),
    ticket_ref: str = Form(""),
    asset_ref: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    # Tickets and assets are both picked by their pretty number
    # (INC-000123 / CI-000123) here, not a raw database id -- matches how
    # every other reference in the UI works post-pretty-URLs.
    resolved_id: int | None = None
    if linked_type == "ticket":
        ticket = await ticket_service.get_ticket_by_ref(tenant_db, ticket_ref.strip()) if ticket_ref.strip() else None
        resolved_id = ticket.id if ticket is not None else None
    elif linked_type == "asset":
        asset = await asset_service.get_asset_by_ref(tenant_db, asset_ref.strip()) if asset_ref.strip() else None
        resolved_id = asset.id if asset is not None else None

    if linked_type in LINKED_TYPES and resolved_id is not None:
        await service.add_link(tenant_db, document_id, linked_type, resolved_id, ctx.user.id)
        if linked_type == "ticket" and doc is not None:
            await _log_ticket_link_activity(tenant_db, linked=True, document=doc, ticket_id=resolved_id, user_id=ctx.user.id)
    return RedirectResponse(f"/documents/{doc.doc_number if doc else document_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{document_id:int}/unlink/{link_id:int}")
async def unlink_document(
    document_id: int,
    link_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    link = await service.remove_link(tenant_db, link_id)
    if link is not None and link.linked_type == "ticket":
        await _log_ticket_link_activity(tenant_db, linked=False, document=link.document, ticket_id=link.linked_id, user_id=ctx.user.id)
    doc_ref = link.document.doc_number if link is not None else document_id
    return RedirectResponse(f"/documents/{doc_ref}", status_code=status.HTTP_303_SEE_OTHER)
