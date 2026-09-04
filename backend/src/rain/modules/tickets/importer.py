"""CSV/JSON ticket import: parse -> user maps columns to fields (auto-
suggested by header name) -> commit. No asset_type selector (ticket_type
is a mapped column instead, same as it's a Form field on the manual "New
ticket" screen) -- a row with no dedup match becomes a new ticket via
rain.modules.tickets.service.create_ticket, same choke point the manual
form and syslog auto-promotion already share (Platform Event rules,
watcher-add, etc. all still fire per imported ticket).

Change tickets are deliberately rejected here rather than silently
created without one: rain.modules.tickets.router.create_ticket enforces
"a change must name a real, usable approval flow" before calling
service.create_ticket at all, and there's no sane way to ask a CSV row to
carry a flow selection the way the manual form's dropdown does. A change
ticket needing bulk import can still be built with tools that speak the
approval-flow API/DB directly; this importer just isn't that tool.

Deduplication ("Dedup key" -> Ticket.external_finding_key, migration
0050) is opt-in per import: map a column to it and every row is looked
up by that value before deciding what to do, exactly mirroring
rain.modules.assets.importer's own external_id upsert (same select-
then-branch shape, same reliance on the column's real DB-level
UniqueConstraint to catch a race rather than a fancier atomic upsert --
see that module's own docstring). Leave "Dedup key" unmapped and
behavior is unchanged from before this existed: every row always
creates a new ticket. A single mapped column is deliberately the whole
mechanism -- there's no multi-column composite-key builder here, so a
source whose natural identity spans several fields (a vulnerability
scanner's host+port+plugin-ID, say) needs that composed into one column
before it reaches this importer (a spreadsheet formula ahead of upload
is the expected way, not something this code tries to do for you).

On a match: an already-open ticket is left alone (title/description/
severity are never overwritten by a later import -- a human may have
already triaged them) but its custom field values still update, so a
"last seen" or "current CVSS score" field stays current on every
re-import. A *closed* match is treated as a regression: reopened (into
whichever status key "open" resolves to for this tenant -- if that key
doesn't exist, left closed with a warning rather than guessed at),
flagged is_problematic (this is by definition no longer a one-off), and
commented with which import row caused it."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field as dc_field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from rain.modules.assets.schemas import coerce_field_value
from rain.modules.tickets import service
from rain.modules.tickets.schemas import SEVERITIES, TICKET_TYPES


def sniff_headers(raw: bytes, fmt: str) -> list[str]:
    if fmt == "json":
        data = json.loads(raw.decode("utf-8"))
        return list(data[0].keys()) if data else []
    text = raw.decode("utf-8-sig")
    return next(csv.reader(io.StringIO(text)), [])


def parse_rows(raw: bytes, fmt: str) -> list[dict[str, Any]]:
    if fmt == "json":
        return json.loads(raw.decode("utf-8"))
    text = raw.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


# The status a regression is reopened into. Not configurable per import
# (yet) -- every tenant this importer has actually been exercised
# against provisions this key, and get_status_by_key's own contract
# already covers the "tenant renamed/removed it" case gracefully (see
# below: update_status returns False rather than raising, surfaced as a
# warning instead of guessing at a replacement).
_REOPEN_STATUS_KEY = "open"


@dataclass
class ImportResult:
    created: int = 0
    reopened: int = 0
    unchanged: int = 0
    errors: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)


async def commit_import(
    db: AsyncSession,
    *,
    rows: list[dict[str, Any]],
    mapping: dict[str, str],
    actor_id: int,
) -> ImportResult:
    """mapping: target ("ticket_type" | "title" | "description" | "severity" |
    "upsert_key" | "field_<id>") -> source column name. ticket_type and
    title are required per row; everything else falls back the same way
    the manual form does (severity defaults to "medium", description to
    None). "upsert_key" is optional -- see this module's own docstring
    for the dedup semantics it turns on when mapped."""
    result = ImportResult()
    fields_by_id = {f.id: f for f in await service.ticket_fields(db)}
    key_col = mapping.get("upsert_key")

    for i, row in enumerate(rows, start=1):
        try:
            type_col = mapping.get("ticket_type")
            raw_type = str(row.get(type_col, "")).strip().lower() if type_col else ""
            if raw_type not in TICKET_TYPES:
                result.errors.append(f"row {i}: missing or unrecognized ticket_type '{raw_type}'")
                continue
            if raw_type == "change":
                result.errors.append(f"row {i}: change tickets need an approval flow -- create those manually")
                continue

            title_col = mapping.get("title")
            title = str(row.get(title_col, "")).strip() if title_col else ""
            if not title:
                result.errors.append(f"row {i}: missing title")
                continue

            desc_col = mapping.get("description")
            description = str(row.get(desc_col, "")).strip() or None if desc_col else None

            severity = "medium"
            sev_col = mapping.get("severity")
            if sev_col and row.get(sev_col):
                raw_severity = str(row[sev_col]).strip().lower()
                if raw_severity in SEVERITIES:
                    severity = raw_severity
                else:
                    result.warnings.append(f"row {i}: unrecognized severity '{raw_severity}' -- defaulted to 'medium'")

            key = str(row.get(key_col, "")).strip().lower() if key_col else ""
            existing = await service.get_ticket_by_external_key(db, key) if key else None

            if existing is None:
                ticket = await service.create_ticket(
                    db,
                    ticket_type=raw_type,
                    title=title,
                    description=description,
                    severity=severity,
                    reporter_user_id=actor_id,
                    external_finding_key=key or None,
                )
                result.created += 1
            else:
                ticket = existing
                status_row = await service.get_status_by_key(db, ticket.status)
                if status_row is not None and status_row.is_closed:
                    reopened = await service.update_status(db, ticket, _REOPEN_STATUS_KEY, changed_by_user_id=actor_id)
                    if reopened:
                        await service.add_comment(
                            db, ticket.id, actor_id, f"Reopened: finding reappeared in an import (row {i})."
                        )
                        # A finding that regressed after being marked
                        # resolved is by definition no longer a one-off --
                        # same flag the "mark problematic" quick action
                        # and Platform Response Rule action already use.
                        await service.update_problematic(db, ticket, True, changed_by_user_id=actor_id)
                        result.reopened += 1
                    else:
                        result.warnings.append(
                            f"row {i}: matched {ticket.ticket_number} (closed) but this tenant has no "
                            f"'{_REOPEN_STATUS_KEY}' status configured -- left closed"
                        )
                        result.unchanged += 1
                else:
                    result.unchanged += 1

            values: dict[int, Any] = {}
            for field_id, field_def in fields_by_id.items():
                col = mapping.get(f"field_{field_id}")
                if col and col in row:
                    values[field_id] = coerce_field_value(field_def.field_type, row.get(col))
            if values:
                await service.set_ticket_field_values(db, ticket, values)
                await db.commit()

        except Exception as exc:  # one bad row shouldn't abort the whole import
            result.errors.append(f"row {i}: {exc}")

    return result
