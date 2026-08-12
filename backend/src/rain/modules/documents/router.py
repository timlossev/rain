from __future__ import annotations

import io
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.modules.documents import service, storage
from rain.modules.documents.schemas import LINKED_TYPES, MAX_UPLOAD_BYTES
from rain.web.nav import build_nav_context
from rain.web.pdf import render_pdf
from rain.web.templating import templates

router = APIRouter(prefix="/documents")


@router.get("", response_class=HTMLResponse)
async def list_documents(
    request: Request,
    search: str | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    documents = await service.list_documents(tenant_db, search=search)
    return templates.TemplateResponse(
        request, "documents/list.html", {**nav, "ctx": ctx, "documents": documents, "search": search or ""}
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
    file: UploadFile,
    title: str = Form(...),
    description: str = Form(""),
    linked_type: str = Form(""),
    linked_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        nav = await build_nav_context(ctx)
        return templates.TemplateResponse(
            request,
            "documents/form.html",
            {**nav, "ctx": ctx, "linked_type": linked_type, "linked_id": linked_id, "error": "File too large (max 25MB)."},
            status_code=400,
        )

    key = storage.make_storage_key(ctx.active_tenant.schema_name, file.filename or "file")
    storage.get_storage().save(key, data)

    doc = await service.create_document(
        tenant_db,
        title=title.strip(),
        description=description.strip() or None,
        filename=file.filename or "file",
        storage_key=key,
        mime_type=file.content_type,
        size_bytes=len(data),
        uploaded_by=ctx.user.id,
    )

    if linked_type in LINKED_TYPES and linked_id:
        await service.add_link(tenant_db, doc.id, linked_type, int(linked_id), ctx.user.id)
        if linked_type == "asset":
            return RedirectResponse(f"/assets/{linked_id}/edit", status_code=status.HTTP_303_SEE_OTHER)
        return RedirectResponse(f"/tickets/{linked_id}", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse(f"/documents/{doc.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{document_id:int}", response_class=HTMLResponse)
async def document_detail(
    request: Request,
    document_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    doc = await service.get_document(tenant_db, document_id)
    if doc is None:
        return RedirectResponse("/documents", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request, "documents/detail.html", {**nav, "ctx": ctx, "doc": doc, "linked_types": LINKED_TYPES}
    )


@router.get("/{document_id:int}/pdf")
async def document_pdf(
    document_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is None:
        return RedirectResponse("/documents", status_code=status.HTTP_303_SEE_OTHER)
    pdf_bytes = render_pdf(
        "pdf/document.html",
        {
            "doc": doc,
            "doc_kind": "Document",
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


@router.post("/{document_id:int}/link")
async def link_document(
    document_id: int,
    linked_type: str = Form(...),
    linked_id: int = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    if linked_type in LINKED_TYPES:
        await service.add_link(tenant_db, document_id, linked_type, linked_id, ctx.user.id)
    return RedirectResponse(f"/documents/{document_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{document_id:int}/unlink/{link_id:int}")
async def unlink_document(
    document_id: int,
    link_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    await service.remove_link(tenant_db, link_id)
    return RedirectResponse(f"/documents/{document_id}", status_code=status.HTTP_303_SEE_OTHER)
