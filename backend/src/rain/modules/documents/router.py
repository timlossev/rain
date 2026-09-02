from __future__ import annotations

import io
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.convertors import Convertor, register_url_convertor

from rain.core.pagination import paginate
from rain.core.query_params import optional_int
from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.core.tenant_config import get_tenant_config
from rain.core.user_names import is_assignable_user, list_assignable_users, resolve_user_names
from rain.modules.assets import service as asset_service
from rain.modules.calendar import service as calendar_service
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
    tag: str | None = None,
    page: int = 1,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    page_size = await get_tenant_config(tenant_db, "default_page_size")
    doc_page = await paginate(
        tenant_db, service.document_list_stmt(search=search, tag=tag), page=page, page_size=page_size
    )
    # Both cheap, tenant-wide lookups backing the list's own flag icons/tag
    # filter -- see their own docstrings (calendar_service.
    # document_ids_with_calendar_entries, service.list_all_tags).
    all_tags = await service.list_all_tags(tenant_db)
    calendar_linked_ids = await calendar_service.document_ids_with_calendar_entries(tenant_db)
    shareable_label = await get_tenant_config(tenant_db, "portal_shareable_documents_label")
    return templates.TemplateResponse(
        request,
        "documents/list.html",
        {
            **nav,
            "ctx": ctx,
            "page": doc_page,
            "search": search or "",
            "selected_tag": tag or "",
            "all_tags": all_tags,
            "calendar_linked_ids": calendar_linked_ids,
            "shareable_label": shareable_label,
        },
    )


_KANBAN_DOC_CAP = 500


@router.get("/kanban", response_class=HTMLResponse)
async def documents_kanban(
    request: Request,
    search: str | None = None,
    group_by: str = "tag",  # "tag" | "owner"
    owner_group: str | None = None,
    filter_tag: str | None = None,
    filter_owner: str | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Documents, grouped into Kanban columns instead of the list view's
    table rows -- group_by picks what the columns are, the same two-mode
    shape rain.modules.tickets.router.kanban_board already established
    for tickets:

    "tag" (default): a normalized (service.normalize_tag), deduplicated-
    across-documents view of every tag in use, plus a leading
    "Uncategorized" column for documents with none. A document with
    several tags appears as its own card in each one -- dragging a card
    between tag columns retags it (service.retag below), a targeted swap
    (remove the tag it came from, add the one it's dropped on) that
    leaves every other tag on the document untouched, not a wholesale
    replace. filter_owner (only meaningful here) narrows the underlying
    document set to one person's own documents first -- the board's
    *columns* are still tags, this is a plain filter on the other axis,
    not a second grouping dimension.

    "owner": a workload view, one column per this tenant's assignable
    users (rain.core.user_names.list_assignable_users, the same
    candidate set the tickets board's own assignee mode uses) plus a
    leading "No owner" column, optionally narrowed to one Group's own
    members via owner_group -- same "too many users otherwise" filter
    the tickets board grew for assignee mode. Dragging a card between
    owner columns reassigns it (service.update_owner), a single-valued
    move, unlike tag mode: a document has exactly one owner_user_id.
    filter_tag (only meaningful here), the mirror of filter_owner above,
    narrows the document set to one tag first.

    Either filter is accepted regardless of group_by but only ever
    rendered as a control in the mode it doesn't already group by --
    filtering "group by tag" by a single tag, or "group by owner" by a
    single owner, would just hide every other column for no reason."""
    nav = await build_nav_context(ctx)
    # str, not int | None -- see rain.core.query_params.optional_int's own
    # docstring for why (both <select>s' "clear" options submit an empty
    # string once cleared, which int | None rejects as a raw 422 instead
    # of "no filter").
    owner_group = optional_int(owner_group)
    filter_owner = optional_int(filter_owner)
    group_by = group_by if group_by in ("tag", "owner") else "tag"
    stmt = service.document_list_stmt(
        search=search,
        tag=filter_tag if group_by == "owner" else None,
        owner_user_id=filter_owner if group_by == "tag" else None,
    ).limit(_KANBAN_DOC_CAP + 1)
    result = await tenant_db.execute(stmt)
    docs = list(result.scalars())
    truncated = len(docs) > _KANBAN_DOC_CAP
    docs = docs[:_KANBAN_DOC_CAP]

    # Both candidate lists are fetched regardless of group_by: each backs
    # this mode's own columns in one direction and the *other* mode's
    # cross-filter dropdown in the other.
    all_tags = await service.list_all_tags(tenant_db)
    all_assignable_users = await list_assignable_users(ctx.active_tenant.id)

    tag_columns: dict[str, list] = {}
    tag_labels: list[str] = []
    owner_groups: list = []
    owner_users: list = []
    owner_columns: dict[str, list] = {}
    extra_owner_ids: list[int] = []

    if group_by == "tag":
        tag_columns["uncategorized"] = []
        for doc in docs:
            if not doc.tags:
                tag_columns["uncategorized"].append(doc)
                continue
            # A document with more than one tag shows up once per tag --
            # see this route's own docstring for why a swap, not a
            # wholesale replace, is what dragging one of those cards does.
            for raw_tag in doc.tags:
                label = service.normalize_tag(raw_tag)
                tag_columns.setdefault(label, []).append(doc)
        tag_labels = sorted(k for k in tag_columns if k != "uncategorized")
    else:
        owner_groups = await service.list_groups(tenant_db)
        owner_users = all_assignable_users
        if owner_group is not None:
            member_ids = await service.group_member_ids(tenant_db, owner_group)
            owner_users = [u for u in owner_users if u.id in member_ids]
        known_owner_ids = {u.id for u in owner_users}
        owner_columns = {"unowned": []}
        for u in owner_users:
            owner_columns[str(u.id)] = []
        for doc in docs:
            if doc.owner_user_id is None:
                owner_columns["unowned"].append(doc)
            elif doc.owner_user_id in known_owner_ids:
                owner_columns[str(doc.owner_user_id)].append(doc)
            else:
                # Owned by someone no longer assignable to this tenant, or
                # simply outside the currently selected group -- same
                # "extra column, not a drop target" treatment the tickets
                # board gives an equivalent case.
                owner_columns.setdefault(str(doc.owner_user_id), []).append(doc)
                if doc.owner_user_id not in extra_owner_ids:
                    extra_owner_ids.append(doc.owner_user_id)

    owner_names = await resolve_user_names({d.owner_user_id for d in docs} | set(extra_owner_ids))
    calendar_linked_ids = await calendar_service.document_ids_with_calendar_entries(tenant_db)
    shareable_label = await get_tenant_config(tenant_db, "portal_shareable_documents_label")

    return templates.TemplateResponse(
        request,
        "documents/kanban.html",
        {
            **nav,
            "ctx": ctx,
            "search": search or "",
            "truncated": truncated,
            # Zero documents matching the current search/filters is a
            # legitimate, unremarkable state -- the board still renders,
            # every column just says "No documents." individually already;
            # this is only for a single clearer banner above the (otherwise
            # all-empty-looking) board, not an error of any kind.
            "no_matches": not docs,
            "selected_group_by": group_by,
            "tag_columns": tag_columns,
            "tag_labels": tag_labels,
            "owner_groups": owner_groups,
            "selected_owner_group": owner_group,
            "owner_users": owner_users,
            "owner_columns": owner_columns,
            "extra_owner_ids": extra_owner_ids,
            "owner_names": owner_names,
            "all_tags": all_tags,
            "selected_filter_tag": filter_tag or "",
            "all_assignable_users": all_assignable_users,
            "selected_filter_owner": filter_owner,
            "calendar_linked_ids": calendar_linked_ids,
            "shareable_label": shareable_label,
        },
    )


@router.post("/{document_id:int}/kanban-tag")
async def documents_kanban_retag(
    document_id: int,
    from_tag: str = Form(""),
    to_tag: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Kanban's "group by tag" view (documents_kanban above): dragging a
    card between two tag columns, or into "Uncategorized" (an empty
    to_tag). Mirrors kanban_update_status/kanban_update_assignee on the
    tickets board -- JSON instead of a redirect, so the board moves the
    card in the DOM itself rather than reloading the whole page."""
    doc = await service.get_document(tenant_db, document_id)
    if doc is None:
        return JSONResponse({"ok": False, "error": "Document not found."}, status_code=404)
    await service.retag(tenant_db, doc, from_tag=from_tag, to_tag=to_tag)
    return {"ok": True, "tags": doc.tags, "tag_label": service.normalize_tag(to_tag) if to_tag else None}


@router.post("/{document_id:int}/kanban-owner")
async def documents_kanban_owner(
    document_id: int,
    new_owner_user_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    """Kanban's "group by owner" view (documents_kanban above): dragging a
    card into a different owner column, or into "No owner". Re-checks
    is_assignable_user() server-side before accepting a drop, same
    reasoning as the tickets board's own kanban_update_assignee -- the
    board only ever *offers* this tenant's assignable users as columns,
    but a crafted POST could still name an arbitrary id."""
    doc = await service.get_document(tenant_db, document_id)
    if doc is None:
        return JSONResponse({"ok": False, "error": "Document not found."}, status_code=404)
    new_id = int(new_owner_user_id) if new_owner_user_id else None
    if new_id is not None and not await is_assignable_user(new_id, ctx.active_tenant.id):
        return JSONResponse({"ok": False, "error": "Not assignable to this tenant."}, status_code=400)
    await service.update_owner(tenant_db, doc, new_id)
    names = await resolve_user_names({new_id}) if new_id is not None else {}
    return {"ok": True, "owner_user_id": new_id, "owner_name": names.get(new_id, "No owner")}


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
    tags: str = Form(""),
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
        tags=service.parse_tags(tags),
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

    # "Refresh from webhook on view": re-runs the same call/diff/save
    # refresh_from_webhook does for the manual button, but before this GET
    # even reads the stored body -- a successful call has already
    # overwritten storage by the time body_text is read below, so the
    # freshly-fetched copy is what renders; a failed call never touches
    # storage at all, so body_text below reads whatever was already
    # there. webhook_refresh_error is only set to flash that failure --
    # it's not a reason to fail the page itself.
    webhook_refresh_error = None
    if doc.refresh_on_view and doc.webhook_id and textbody.body_kind(doc.filename) is not None:
        outcome = await service.refresh_from_webhook(tenant_db, doc)
        if not outcome.ok:
            webhook_refresh_error = outcome.error

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
    calendar_entries = await calendar_service.list_entries_for_document(tenant_db, doc.id)
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
            "calendar_entries": calendar_entries,
            "webhook_refresh_error": webhook_refresh_error,
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


@router.post("/{document_id:int}/tags")
async def update_document_tags(
    document_id: int,
    tags: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is not None:
        await service.update_tags(tenant_db, doc, service.parse_tags(tags))
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


@router.post("/{document_id:int}/sharing")
async def update_document_sharing(
    document_id: int,
    is_shareable: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is not None:
        await service.update_sharing(tenant_db, doc, is_shareable)
    return RedirectResponse(f"/documents/{doc.doc_number if doc else document_id}?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{document_id:int}/landing-page")
async def update_document_landing_page(
    document_id: int,
    show_on_landing_page: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is not None:
        await service.update_landing_page_flag(tenant_db, doc, show_on_landing_page)
    return RedirectResponse(f"/documents/{doc.doc_number if doc else document_id}?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{document_id:int}/refresh-on-view")
async def update_document_refresh_on_view(
    document_id: int,
    refresh_on_view: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is not None:
        await service.update_refresh_on_view_flag(tenant_db, doc, refresh_on_view)
    return RedirectResponse(f"/documents/{doc.doc_number if doc else document_id}?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{document_id:int}/webhook-config")
async def set_document_webhook_config(
    document_id: int,
    webhook_id: str = Form(""),
    alert_on_change: bool = Form(False),
    webhook_response_is_json: bool = Form(False),
    webhook_json_path: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    doc = await service.get_document(tenant_db, document_id)
    if doc is not None:
        await service.update_webhook_config(
            tenant_db,
            doc,
            webhook_id=int(webhook_id) if webhook_id else None,
            alert_on_change=alert_on_change,
            response_is_json=webhook_response_is_json,
            json_path=webhook_json_path.strip() or None,
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
    if outcome.json_note:
        query += f"&json_note={quote(outcome.json_note)}"
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
