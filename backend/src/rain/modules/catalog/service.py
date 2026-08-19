"""Service Catalog: a tenant-defined self-service catalog of requestable
items, each an up-to-10-question form (rain.modules.catalog.schemas.
MAX_CATALOG_FIELDS) that produces a ticket on submission. Two consumers
share every function here -- rain.modules.catalog.router (the main app's
/catalog, under Records Authority) and rain.modules.portal.router (the
customer-facing portal's Catalog tab) -- so a submission behaves
identically regardless of where it came in.

A field's value can come from free-form entry, or be sourced from an
existing Document (resolve_field_source) -- either used as-is, or narrowed
with a regex or a JSONPath. See ServiceCatalogField's own docstring
(rain.db.tenant_models) for the exact semantics.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dataclass_field

from jsonpath_ng.ext import parse as parse_jsonpath
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import ApprovalFlow, ServiceCatalogField, ServiceCatalogItem, Ticket
from rain.modules.assets.schemas import coerce_field_value
from rain.modules.documents import service as document_service
from rain.modules.documents import storage, textbody
from rain.modules.tickets import service as ticket_service

#: A resolved select's option list, or a regex/JSONPath match list, is
#: capped here -- a runaway pattern (e.g. `.` against a huge document)
#: shouldn't be able to render a multi-thousand-row <select>.
_MAX_OPTIONS = 200
#: A non-select prefill is capped the same way tickets/documents already
#: cap other free text pulled from an external source (see e.g.
#: rain.modules.tickets.listener truncating message/raw to 8000 chars).
_MAX_PREFILL_CHARS = 4000


def _catalog_item_stmt():
    return select(ServiceCatalogItem).options(
        selectinload(ServiceCatalogItem.fields).selectinload(ServiceCatalogField.source_document),
        # .steps too, not just approval_flow itself -- ticket_service.
        # start_approval's own db.get(ApprovalFlow, ..., options=[selectinload(
        # ApprovalFlow.steps)]) call, made later in the same request/session
        # once a submission is confirmed valid, finds this same ApprovalFlow
        # row already in the session's identity map (loaded here, to show
        # e.g. "routed through <flow.name>" in the form's help text) and
        # returns that cached instance as-is rather than re-querying with
        # its own eager-load option -- Session.get()'s `options` only takes
        # effect on a load it actually performs. Leaving .steps unloaded on
        # that shared instance meant start_approval's own `if not flow.
        # steps` crashed (MissingGreenlet -- a plain attribute read
        # synchronously lazy-loading is never safe under the async driver
        # regardless of which code touches it first), confirmed live before
        # this was added.
        selectinload(ServiceCatalogItem.approval_flow).selectinload(ApprovalFlow.steps),
    )


async def list_catalog_items(db: AsyncSession, *, active_only: bool = False) -> list[ServiceCatalogItem]:
    stmt = _catalog_item_stmt().order_by(ServiceCatalogItem.sort_order, ServiceCatalogItem.name)
    if active_only:
        stmt = stmt.where(ServiceCatalogItem.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().unique())


async def get_catalog_item(db: AsyncSession, item_id: int) -> ServiceCatalogItem | None:
    result = await db.execute(_catalog_item_stmt().where(ServiceCatalogItem.id == item_id))
    return result.scalar_one_or_none()


async def get_catalog_item_by_key(db: AsyncSession, key: str) -> ServiceCatalogItem | None:
    result = await db.execute(_catalog_item_stmt().where(ServiceCatalogItem.key == key))
    return result.scalar_one_or_none()


async def delete_catalog_item(db: AsyncSession, item: ServiceCatalogItem) -> None:
    await db.delete(item)  # cascades to service_catalog_fields
    await db.commit()


async def set_active(db: AsyncSession, item: ServiceCatalogItem, is_active: bool) -> None:
    item.is_active = is_active
    await db.commit()


async def replace_catalog_fields(db: AsyncSession, item: ServiceCatalogItem, form, *, max_fields: int) -> None:
    """Rebuilds item.fields from a submitted admin form -- shares the
    "server pre-renders N rows keyed by 1-based index, a row with no
    field_key is simply skipped" shape as admin.router._replace_approval_
    steps, just with more columns per row.

    item.fields.clear() (not item.fields = new_fields) -- reading item.
    fields at all requires it to already be loaded: on an already-flushed
    item whose .fields was never touched, that read needs to lazy-load it
    from the DB first, and that fails synchronously under asyncpg's async
    driver (MissingGreenlet, confirmed live). A still-transient item
    doesn't have this problem (nothing to load, it doesn't exist in the
    DB yet, so its .fields is safely just []), which is why a caller
    building a brand new item calls this before its first add()/flush()
    rather than after; an edit's item already has .fields eager-loaded by
    the time it gets here (rain.modules.catalog.service.get_catalog_item),
    so reading it is safe there too -- either way, by the time this
    function runs, item.fields is never in the one state (persistent,
    unloaded) that breaks. .clear() (relying on the relationship's own
    cascade="all, delete-orphan" to schedule each removed row for
    deletion) rather than reassignment is just the more conventional way
    to empty an already-loaded collection; the two are equivalent once
    it's already loaded.

    The intervening flush (only when there was something to clear) lands
    those deletes before the new rows below get inserted, in the same
    spirit as admin.router._replace_approval_steps's own delete-then-
    flush-then-add sequence -- an edit that keeps one row's field_key but
    changes everything else about it would otherwise risk colliding with
    service_catalog_fields' own unique constraint if the old row's DELETE
    hasn't actually reached the DB yet when the new row's INSERT runs in
    the same flush. Caller still needs to commit."""
    if item.fields:
        item.fields.clear()
        await db.flush()

    sort_order = 0
    for i in range(1, max_fields + 1):
        field_key = str(form.get(f"field_key_{i}", "")).strip().lower()
        if not field_key:
            continue
        label = str(form.get(f"label_{i}", "")).strip() or field_key
        field_type = str(form.get(f"field_type_{i}", "text")).strip()
        raw_options = str(form.get(f"select_options_{i}", ""))
        options = [o.strip() for o in raw_options.split(",") if o.strip()] if field_type == "select" else None
        source_document_id = str(form.get(f"source_document_id_{i}", "")).strip()
        source_mode = str(form.get(f"source_mode_{i}", "")).strip()
        source_expression = str(form.get(f"source_expression_{i}", "")).strip()
        db.add(
            ServiceCatalogField(
                catalog_item=item,
                field_key=field_key,
                label=label,
                field_type=field_type,
                select_options=options,
                is_required=bool(form.get(f"is_required_{i}")),
                sort_order=sort_order,
                source_document_id=int(source_document_id) if source_document_id and source_mode else None,
                source_mode=source_mode or None,
                source_expression=source_expression if source_mode in ("regex", "jsonpath") else None,
            )
        )
        sort_order += 1


# --------------------------------------------------- document sourcing ---


@dataclass
class ResolvedSource:
    """The outcome of evaluating one field's source_mode/source_expression
    against its source_document -- shared by the live admin Preview button
    (nothing saved yet, see rain.modules.admin.router's preview route) and
    the real render/submit path (resolve_answers below). `ok=False` means
    "couldn't resolve anything" (bad pattern, missing document, etc.);
    callers render that as an inline error in Preview, but treat it as
    just "no value/options" (fall back to static config) everywhere
    else -- a document going missing or a regex typo shouldn't be able to
    break the form for an end user filling it in."""

    ok: bool
    value: str | None = None
    options: list[str] = dataclass_field(default_factory=list)
    error: str | None = None
    document_label: str | None = None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


async def resolve_field_source(
    db: AsyncSession, *, document_id: int | None, mode: str | None, expression: str | None, is_select: bool
) -> ResolvedSource:
    if not document_id or not mode:
        return ResolvedSource(ok=True)

    doc = await document_service.get_document(db, document_id)
    if doc is None:
        return ResolvedSource(ok=False, error="That document no longer exists.")
    label = f"{doc.doc_number}: {doc.title}"

    if textbody.body_kind(doc.filename) is None:
        return ResolvedSource(
            ok=False, error=f"{doc.doc_number} isn't a text/Markdown/JSON document -- its content can't be read.",
            document_label=label,
        )
    try:
        content = textbody.decode_body(storage.get_storage().read(doc.storage_key))
    except FileNotFoundError:
        return ResolvedSource(ok=False, error=f"{doc.doc_number}'s stored file is missing.", document_label=label)

    if mode == "content":
        if is_select:
            options = _dedupe([line.strip() for line in content.splitlines() if line.strip()])
            return ResolvedSource(ok=True, options=options[:_MAX_OPTIONS], document_label=label)
        return ResolvedSource(ok=True, value=content.strip()[:_MAX_PREFILL_CHARS], document_label=label)

    if mode == "regex":
        if not expression:
            return ResolvedSource(ok=False, error="A regex pattern is required.", document_label=label)
        try:
            # MULTILINE only, deliberately not also DOTALL -- content is
            # always a whole (potentially multi-line) document body, so
            # ^/$ need to anchor per line for the common "one option per
            # line" style pattern (e.g. ^(us-.*)$ against a document of
            # one region per line) to match each line separately at all.
            # DOTALL would let a greedy .* under that same pattern cross
            # newlines and swallow the rest of the document as a single
            # match instead -- confirmed live against exactly that
            # pattern before removing it.
            pattern = re.compile(expression, re.MULTILINE)
        except re.error as exc:
            return ResolvedSource(ok=False, error=f"Invalid regex: {exc}", document_label=label)
        matches = [(m.group(1) if m.groups() else m.group(0)) for m in pattern.finditer(content)]
        if is_select:
            return ResolvedSource(ok=True, options=_dedupe(matches)[:_MAX_OPTIONS], document_label=label)
        return ResolvedSource(ok=True, value=matches[0][:_MAX_PREFILL_CHARS] if matches else None, document_label=label)

    if mode == "jsonpath":
        if not expression:
            return ResolvedSource(ok=False, error="A JSONPath expression is required.", document_label=label)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            return ResolvedSource(ok=False, error=f"{doc.doc_number} isn't valid JSON: {exc}", document_label=label)
        try:
            jsonpath_expr = parse_jsonpath(expression)
        # jsonpath-ng's parser is Ply-based -- malformed input doesn't
        # consistently raise JsonPathParserError across every syntax
        # error it can hit (some surface as a plain Exception from Ply
        # itself), so this is caught broadly rather than risking a 500 on
        # an admin's typo while designing a field.
        except Exception as exc:
            return ResolvedSource(ok=False, error=f"Invalid JSONPath: {exc}", document_label=label)
        try:
            matches = [str(m.value) for m in jsonpath_expr.find(data)]
        except Exception as exc:  # same reasoning -- evaluation can also raise a few different types
            return ResolvedSource(ok=False, error=f"Couldn't evaluate that JSONPath: {exc}", document_label=label)
        if is_select:
            return ResolvedSource(ok=True, options=_dedupe(matches)[:_MAX_OPTIONS], document_label=label)
        return ResolvedSource(ok=True, value=matches[0][:_MAX_PREFILL_CHARS] if matches else None, document_label=label)

    return ResolvedSource(ok=False, error=f"Unknown source mode {mode!r}.", document_label=label)


@dataclass
class RenderedField:
    """One field, ready to render into a form -- its static config plus
    whatever resolve_field_source came back with, already merged (dynamic
    options win when non-empty, else the field's own static select_
    options; a resolved value only applies as a prefill when the field
    isn't already document-driven towards options instead)."""

    field: ServiceCatalogField
    options: list[str]
    prefill: str


async def render_fields(db: AsyncSession, item: ServiceCatalogItem) -> list[RenderedField]:
    out: list[RenderedField] = []
    for f in item.fields:
        is_select = f.field_type == "select"
        resolved = await resolve_field_source(
            db, document_id=f.source_document_id, mode=f.source_mode, expression=f.source_expression, is_select=is_select
        )
        options = resolved.options if resolved.options else (f.select_options or [])
        prefill = resolved.value or ""
        out.append(RenderedField(field=f, options=options, prefill=prefill))
    return out


# ----------------------------------------------------------- submission ---


def render_payload(item: ServiceCatalogItem, answers: dict[str, object]) -> str:
    """answers is field_key -> coerced value, already validated (empty/
    None values pruned -- an optional question left blank doesn't appear
    at all, in either format)."""
    present = {k: v for k, v in answers.items() if v is not None and v != ""}
    if item.payload_format == "json":
        return json.dumps(present, indent=2, default=str)
    return "\n".join(f"{k}={v}" for k, v in present.items())


@dataclass
class SubmissionResult:
    ticket: Ticket | None = None
    errors: list[str] = dataclass_field(default_factory=list)


async def submit_catalog_item(
    db: AsyncSession,
    item: ServiceCatalogItem,
    form,
    *,
    reporter_user_id: int | None,
    reported_anonymously: bool = False,
) -> SubmissionResult:
    """Validates the submitted answers against item.fields (required-ness,
    and -- for a document-sourced select -- membership in the currently
    resolved option list, best-effort: a resolution failure at this point
    doesn't block submission, since the alternative is an outage
    somewhere else in the app blocking every catalog request) and, if
    valid, creates the ticket. Returns errors instead of raising -- both
    callers (rain.modules.catalog.router, rain.modules.portal.router)
    render the same form back with those on a validation failure."""
    errors: list[str] = []
    answers: dict[str, object] = {}

    for f in item.fields:
        raw = form.get(f"answer_{f.field_key}")
        raw = raw.strip() if isinstance(raw, str) else raw
        if not raw:
            if f.is_required:
                errors.append(f'"{f.label}" is required.')
            answers[f.field_key] = None
            continue

        if f.field_type == "select":
            resolved = await resolve_field_source(
                db, document_id=f.source_document_id, mode=f.source_mode, expression=f.source_expression, is_select=True
            )
            valid_options = resolved.options if resolved.options else (f.select_options or [])
            if valid_options and raw not in valid_options:
                errors.append(f'"{f.label}": that\'s not one of the current options.')
                continue

        answers[f.field_key] = coerce_field_value(f.field_type, raw)

    if errors:
        return SubmissionResult(errors=errors)

    ticket = await ticket_service.create_ticket(
        db,
        ticket_type=item.ticket_type,
        title=item.name[:255],
        description=render_payload(item, answers),
        severity=item.default_severity,
        reporter_user_id=reporter_user_id,
        reported_anonymously=reported_anonymously,
        source_catalog_item_id=item.id,
    )
    if item.requires_approval:
        await ticket_service.start_approval(db, ticket, item.approval_flow_id)
    return SubmissionResult(ticket=ticket)
