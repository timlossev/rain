from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from jsonpath_ng.ext import parse as parse_jsonpath
from sqlalchemy import Sequence, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import Document, DocumentLink, SyslogEvent
from rain.modules.documents import storage, textbody
from rain.modules.tickets import rules as ticket_rules
from rain.modules.webhooks import service as webhook_service

# Tolerant of a missing or partial zero-pad ("DOC-1" as well as
# "DOC-000001") -- see rain.modules.tickets.service._TICKET_REF_RE.
_DOC_REF_RE = re.compile(r"^DOC-(\d+)$", re.IGNORECASE)

_DIFF_MAX_LINES = 40

# Sanity ceiling, not a real limit anyone should hit -- guards against a
# pasted wall of text (or a stray script) turning "comma-separated tags"
# into hundreds of tsvector lexemes for one document.
_MAX_TAGS = 20
_MAX_TAG_LENGTH = 50


def parse_tags(raw: str) -> list[str]:
    """Comma-separated free text (the form field's own shape) -> a clean
    list: trimmed, empties dropped, deduped case-insensitively (first
    spelling wins -- "Security, security" keeps "Security"), capped at
    _MAX_TAGS. Order preserved otherwise, so re-editing a document's tags
    doesn't shuffle them for no reason."""
    seen: set[str] = set()
    tags: list[str] = []
    for piece in raw.split(","):
        tag = piece.strip()[:_MAX_TAG_LENGTH]
        if not tag or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        tags.append(tag)
        if len(tags) >= _MAX_TAGS:
            break
    return tags


def _content_changed(old_text: str | None, new_text: str) -> bool:
    """Line-based, not a raw string ==. Confirmed live: a plain
    `new_text != old_text` flagged a save as "changed" purely because the
    stored file happened to end in a trailing newline the freshly-
    submitted textarea body didn't -- exactly the class of insignificant,
    not-a-real-edit difference this diff logic needs to ignore (the same
    principle behind not alerting on a metadata-only save, just caught
    one level lower). str.splitlines() treats "x" and "x\\n" as the same
    single line, so this only reports a change when a line's actual
    content differs -- a genuine trailing *blank* line still counts,
    since splitlines() then produces an extra "" entry."""
    if old_text is None:
        return True
    return old_text.splitlines() != new_text.splitlines()


def _diff_summary(old_text: str | None, new_text: str) -> str:
    """A compact unified diff between a document's previous and new
    content, for the "raw" field of the SyslogEvent alert_on_change fires
    (both the webhook-refresh path and a manual edit-and-save) -- lets
    whoever's looking at the live syslog viewer / a promoted ticket see
    *what* changed at a glance instead of just that something did.
    Capped at _DIFF_MAX_LINES rather than embedding the full diff: a
    large document's full diff would dwarf everything else in the feed."""
    diff_lines = list(
        difflib.unified_diff((old_text or "").splitlines(), new_text.splitlines(), lineterm="", n=1)
    )
    if not diff_lines:
        return "(no textual difference)"
    shown = diff_lines[:_DIFF_MAX_LINES]
    summary = "\n".join(shown)
    remaining = len(diff_lines) - len(shown)
    if remaining > 0:
        summary += f"\n... ({remaining} more diff line{'s' if remaining != 1 else ''})"
    return summary


def _extract_json_text(raw_body: str, json_path: str | None) -> tuple[str, str | None]:
    """Backs Document.webhook_response_is_json (refresh_from_webhook
    below). Returns (text_to_save, note) -- note is None on the "worked
    as configured" path, or a short user-facing explanation of why the
    raw response got saved instead, for the caller to flash without ever
    treating it as a hard failure.

    - Invalid JSON: falls back to raw_body verbatim, unparsed any further
      (no CEF/kv-style guessing here -- this field is specifically "the
      admin says this webhook returns JSON," so a parse failure is worth
      surfacing, not silently reinterpreting as something else).
    - No json_path: the whole parsed object, pretty-printed (`indent=2`)
      instead of whatever compact/single-line form the webhook actually
      sent -- this is what makes "just save the response" still produce a
      readable document body.
    - json_path set: same jsonpath-ng.ext parser and broad except as
      rain.modules.catalog.service.resolve_field_source's own "jsonpath"
      mode (its Ply-based parser doesn't consistently raise one exception
      type across every malformed expression) -- a malformed expression or
      a path matching nothing both fall back to the pretty-printed whole
      object, not the raw response, since the JSON itself was valid.
    - A matched value that isn't itself a string (a nested object/array,
      a number) is pretty-printed the same way the "no path" case is --
      there's no single sane "document text" for a non-scalar match
      otherwise.
    """
    try:
        data = json.loads(raw_body)
    except (ValueError, TypeError):
        return raw_body, "Response wasn't valid JSON -- saved verbatim."

    if not json_path:
        return json.dumps(data, indent=2), None

    try:
        matches = parse_jsonpath(json_path).find(data)
    except Exception:
        return json.dumps(data, indent=2), "Invalid JSONPath -- saved the full JSON response instead."
    if not matches:
        return json.dumps(data, indent=2), "JSONPath matched nothing -- saved the full JSON response instead."

    value = matches[0].value
    return (value if isinstance(value, str) else json.dumps(value, indent=2)), None


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
    tags: list[str] | None = None,
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
        tags=tags or [],
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
        # array_to_string: an ARRAY column has no ilike of its own -- this
        # is the list screen's own quick "contains" filter, kept as plain
        # ILIKE like the other two columns here rather than reusing the
        # tsvector search_vector (that's ranked full-text search, this is
        # a simple substring filter over a small, already-paginated list).
        stmt = stmt.where(
            Document.title.ilike(like)
            | Document.doc_number.ilike(like)
            | func.array_to_string(Document.tags, " ").ilike(like)
        )
    return stmt


async def list_documents(db: AsyncSession, *, search: str | None = None) -> list[Document]:
    result = await db.execute(document_list_stmt(search=search))
    return list(result.scalars())


def _document_detail_stmt():
    return select(Document).options(selectinload(Document.links), selectinload(Document.webhook))


async def get_document(db: AsyncSession, document_id: int) -> Document | None:
    result = await db.execute(_document_detail_stmt().where(Document.id == document_id))
    return result.scalar_one_or_none()


async def get_document_by_ref(db: AsyncSession, ref: str) -> Document | None:
    """`ref` is a doc_number ("DOC-000123", or the same with a short/
    unpadded number like "DOC-123") -- the URL scheme document detail
    links use -- or, for back-compat with any link/bookmark built before
    that switch, a bare integer id."""
    ref = ref.strip()
    if ref.isdigit():
        doc = await get_document(db, int(ref))
        if doc is not None:
            return doc
    match = _DOC_REF_RE.match(ref)
    normalized = f"DOC-{int(match.group(1)):06d}" if match else ref
    result = await db.execute(_document_detail_stmt().where(Document.doc_number == normalized))
    return result.scalar_one_or_none()


async def update_body_size(db: AsyncSession, doc: Document, size_bytes: int) -> None:
    doc.size_bytes = size_bytes
    await db.commit()


async def update_description(db: AsyncSession, doc: Document, description: str | None) -> None:
    doc.description = description
    await db.commit()


async def update_tags(db: AsyncSession, doc: Document, tags: list[str]) -> None:
    doc.tags = tags
    await db.commit()


async def update_sharing(db: AsyncSession, doc: Document, is_shareable: bool) -> None:
    doc.is_shareable = is_shareable
    await db.commit()


def shareable_document_list_stmt():
    """Same shape as document_list_stmt above (a plain select(Document),
    safe to hand straight to rain.core.pagination.paginate) -- no
    search/filtering, unlike that one: this backs the client portal's
    "Shareable documents" tab (rain.modules.portal.router.portal_form),
    reachable by an anonymous visitor regardless of portal_require_auth,
    and nothing here is sensitive enough to need filtering beyond
    is_shareable itself."""
    return select(Document).where(Document.is_shareable.is_(True)).order_by(Document.title)


async def list_shareable_documents(db: AsyncSession) -> list[Document]:
    result = await db.execute(shareable_document_list_stmt())
    return list(result.scalars())


async def update_landing_page_flag(db: AsyncSession, doc: Document, show_on_landing_page: bool) -> None:
    doc.show_on_landing_page = show_on_landing_page
    await db.commit()


async def list_landing_page_documents(db: AsyncSession) -> list[Document]:
    """Documents flagged "Show on the landing page" (rain.modules.home) --
    ordered by title. [] until at least one is flagged; the landing page
    falls back to its plain "Welcome to <instance>" default in that
    case, same as the client portal's Shareable documents tab only
    appearing once a document opts into that."""
    result = await db.execute(select(Document).where(Document.show_on_landing_page.is_(True)).order_by(Document.title))
    return list(result.scalars())


async def update_webhook_config(
    db: AsyncSession,
    doc: Document,
    *,
    webhook_id: int | None,
    alert_on_change: bool,
    response_is_json: bool = False,
    json_path: str | None = None,
) -> None:
    doc.webhook_id = webhook_id
    doc.alert_on_change = alert_on_change
    doc.webhook_response_is_json = response_is_json
    doc.webhook_json_path = json_path
    await db.commit()


@dataclass
class RefreshOutcome:
    ok: bool
    changed: bool = False
    error: str | None = None
    #: Set when webhook_response_is_json was on but something about that
    #: didn't go as configured (invalid JSON, a bad/empty-matching
    #: JSONPath) -- never a reason to fail the refresh, just something
    #: worth flashing back at whoever clicked "Refresh from webhook".
    json_note: str | None = None


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
    json_note = None
    if doc.webhook_response_is_json:
        new_text, json_note = _extract_json_text(result.body, doc.webhook_json_path)
    changed = _content_changed(old_text, new_text)

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
                raw=f"document #{doc.id} webhook refresh (webhook: {webhook.name})\n\n{_diff_summary(old_text, new_text)}",
            )
            db.add(event)
            await db.commit()
            await ticket_rules.evaluate_and_promote(db, event)

    doc.last_refreshed_at = datetime.now(timezone.utc)
    await db.commit()
    return RefreshOutcome(ok=True, changed=changed, json_note=json_note)


async def update_body(db: AsyncSession, doc: Document, new_text: str) -> bool:
    """Saves a manual inline edit (documents/detail.html's Edit/Save
    flow), with the same alert_on_change wiring refresh_from_webhook
    already has for webhook-detected changes above -- diffed against the
    actual stored content (old_text != new_text), never a timestamp or
    other metadata check, so opening the editor and saving with nothing
    actually changed (a common no-op: previewing, or just clicking Save
    out of habit) doesn't fire a false "content changed" alert. Returns
    whether the content actually changed."""
    try:
        old_text = textbody.decode_body(storage.get_storage().read(doc.storage_key))
    except FileNotFoundError:
        old_text = None
    changed = _content_changed(old_text, new_text)

    data = new_text.encode("utf-8")
    storage.get_storage().save(doc.storage_key, data)
    await update_body_size(db, doc, len(data))

    if changed and doc.alert_on_change:
        event = SyslogEvent(
            host="documents",
            program=doc.doc_number,
            facility=None,
            severity=5,  # notice
            message=f"Document {doc.doc_number} ({doc.title}) content changed",
            raw=f"document #{doc.id} manual edit\n\n{_diff_summary(old_text, new_text)}",
        )
        db.add(event)
        await db.commit()
        await ticket_rules.evaluate_and_promote(db, event)

    return changed


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
