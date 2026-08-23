"""CSV/JSON ticket import: parse -> user maps columns to fields (auto-
suggested by header name) -> commit. Unlike rain.modules.assets.importer,
there's no natural upsert key for a ticket (no external_id concept) and no
asset_type selector (ticket_type is a mapped column instead, same as it's
a Form field on the manual "New ticket" screen) -- every row becomes a new
ticket via rain.modules.tickets.service.create_ticket, same choke point
the manual form and syslog auto-promotion already share (Platform Event
rules, watcher-add, etc. all still fire per imported ticket).

Change tickets are deliberately rejected here rather than silently
created without one: rain.modules.tickets.router.create_ticket enforces
"a change must name a real, usable approval flow" before calling
service.create_ticket at all, and there's no sane way to ask a CSV row to
carry a flow selection the way the manual form's dropdown does. A change
ticket needing bulk import can still be built with tools that speak the
approval-flow API/DB directly; this importer just isn't that tool."""
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


@dataclass
class ImportResult:
    created: int = 0
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
    "field_<id>") -> source column name. ticket_type and title are required
    per row; everything else falls back the same way the manual form does
    (severity defaults to "medium", description to None)."""
    result = ImportResult()
    fields_by_id = {f.id: f for f in await service.ticket_fields(db)}

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

            ticket = await service.create_ticket(
                db,
                ticket_type=raw_type,
                title=title,
                description=description,
                severity=severity,
                reporter_user_id=actor_id,
            )
            result.created += 1

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
