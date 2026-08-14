from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Sequence, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import Document, DocumentLink, SyslogEvent
from rain.modules.documents import storage, textbody
from rain.modules.tickets import correlation as ticket_correlation
from rain.modules.tickets import rules as ticket_rules
from rain.modules.webhooks import service as webhook_service


async def _next_doc_number(db: AsyncSession) -> str:
    seq = Sequence("doc_number_seq")
    next_val = await db.scalar(select(seq.next_value()))
    return f"DOC-{next_val:06d}"


async def create_document(
    db: AsyncSession,
    *,
    title: str,
    description: str | None,
    filename: str,
    storage_key: str,
    mime_type: str | None,
    size_bytes: int,
    uploaded_by: int | None,
) -> Document:
    doc = Document(
        doc_number=await _next_doc_number(db),
        title=title,
        description=description,
        filename=filename,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=size_bytes,
        uploaded_by=uploaded_by,
    )
    db.add(doc)
    await db.commit()
    # No db.refresh(doc) -- see rain.modules.tickets.service.create_ticket
    # for why a refresh after commit is both unnecessary
    # (expire_on_commit=False) and actively broken (loses this session's
    # tenant schema_translate_map on the fresh connection checkout).
    return doc


def document_list_stmt(*, search: str | None = None):
    stmt = select(Document).order_by(Document.created_at.desc())
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Document.title.ilike(like) | Document.doc_number.ilike(like))
    return stmt


async def list_documents(db: AsyncSession, *, search: str | None = None) -> list[Document]:
    result = await db.execute(document_list_stmt(search=search))
    return list(result.scalars())


async def list_webhook_populated(db: AsyncSession) -> list[Document]:
    """Documents with a webhook configured -- the only ones eligible for a
    calendar entry's "refresh this document on occurrence" policy
    (rain.modules.calendar.sweep); backs that picker on the calendar
    entry form."""
    stmt = select(Document).where(Document.webhook_id.is_not(None)).order_by(Document.title)
    result = await db.execute(stmt)
    return list(result.scalars())


def _document_detail_stmt():
    return select(Document).options(selectinload(Document.links), selectinload(Document.webhook))


async def get_document(db: AsyncSession, document_id: int) -> Document | None:
    result = await db.execute(_document_detail_stmt().where(Document.id == document_id))
    return result.scalar_one_or_none()


async def get_document_by_ref(db: AsyncSession, ref: str) -> Document | None:
    """`ref` is a doc_number ("DOC-000123") -- the URL scheme document
    detail links use -- or, for back-compat with any link/bookmark built
    before that switch, a bare integer id."""
    if ref.isdigit():
        doc = await get_document(db, int(ref))
        if doc is not None:
            return doc
    result = await db.execute(_document_detail_stmt().where(Document.doc_number == ref))
    return result.scalar_one_or_none()


async def update_body_size(db: AsyncSession, doc: Document, size_bytes: int) -> None:
    doc.size_bytes = size_bytes
    await db.commit()


async def update_description(db: AsyncSession, doc: Document, description: str | None) -> None:
    doc.description = description
    await db.commit()


async def update_webhook_config(db: AsyncSession, doc: Document, *, webhook_id: int | None, alert_on_change: bool) -> None:
    doc.webhook_id = webhook_id
    doc.alert_on_change = alert_on_change
    await db.commit()


@dataclass
class RefreshOutcome:
    ok: bool
    changed: bool = False
    error: str | None = None


async def refresh_from_webhook(db: AsyncSession, doc: Document) -> RefreshOutcome:
    """Call the document's configured webhook, diff the response against
    what's currently stored, and overwrite on a real change -- the actual
    "populate from webhook" logic, shared by the manual "Refresh from
    webhook" button (documents.router) and a calendar entry's "refresh
    this document on occurrence" policy (calendar.sweep), so there's
    exactly one implementation of what a refresh means. Never raises; the
    caller decides what to do with a failed/no-op outcome (a redirect +
    flash for the button, a log line for the sweep)."""
    if doc.webhook_id is None or textbody.body_kind(doc.filename) is None:
        return RefreshOutcome(ok=False, error="document has no webhook configured")

    webhook = await webhook_service.get_webhook(db, doc.webhook_id)
    if webhook is None:
        return RefreshOutcome(ok=False, error="configured webhook no longer exists")

    result = await webhook_service.call_webhook(webhook)
    if not result.success:
        if webhook.alert_on_failure:
            await webhook_service.alert_webhook_failure(
                db, webhook, result, context=f"document {doc.doc_number} refresh"
            )
        return RefreshOutcome(ok=False, error=result.error or f"HTTP {result.status_code}")

    try:
        old_text = textbody.decode_body(storage.get_storage().read(doc.storage_key))
    except FileNotFoundError:
        old_text = None
    new_text = result.body
    changed = new_text != old_text

    if changed:
        data = new_text.encode("utf-8")
        storage.get_storage().save(doc.storage_key, data)
        await update_body_size(db, doc, len(data))

        if doc.alert_on_change:
            event = SyslogEvent(
                host="documents",
                program=doc.doc_number,
                facility=None,
                severity=5,  # notice
                message=f"Document {doc.doc_number} ({doc.title}) content changed via webhook refresh",
                raw=f"document #{doc.id} webhook refresh diff (webhook: {webhook.name})",
            )
            db.add(event)
            await db.commit()
            matched_rule = await ticket_rules.find_matching_rule(db, event)
            if matched_rule is not None:
                await ticket_rules.apply_rule(db, matched_rule, event)
            await ticket_correlation.evaluate_correlation_rules(db, event)

    doc.last_refreshed_at = datetime.now(timezone.utc)
    await db.commit()
    return RefreshOutcome(ok=True, changed=changed)


async def delete_document(db: AsyncSession, document: Document) -> None:
    await db.delete(document)  # cascades to document_links
    await db.commit()


async def add_link(db: AsyncSession, document_id: int, linked_type: str, linked_id: int, created_by: int | None) -> DocumentLink:
    link = DocumentLink(document_id=document_id, linked_type=linked_type, linked_id=linked_id, created_by=created_by)
    db.add(link)
    await db.commit()
    return link


async def remove_link(db: AsyncSession, link_id: int) -> DocumentLink | None:
    """Returns the now-deleted link (document eager-loaded) rather than
    None on success -- the caller (documents/router.py) needs
    linked_type/linked_id/document.title *after* the delete to decide
    whether to log it to a ticket's activity feed, and a plain id isn't
    enough to look either back up post-delete."""
    link = await db.get(DocumentLink, link_id, options=[selectinload(DocumentLink.document)])
    if link is not None:
        await db.delete(link)
        await db.commit()
    return link


async def links_for(db: AsyncSession, linked_type: str, linked_id: int) -> list[DocumentLink]:
    stmt = (
        select(DocumentLink)
        .where(DocumentLink.linked_type == linked_type, DocumentLink.linked_id == linked_id)
        .options(selectinload(DocumentLink.document))
        .order_by(DocumentLink.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars())
