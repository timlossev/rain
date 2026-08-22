"""CSV/JSON/Excel ticket export with a caller-supplied column set -- which
fields, what header each one gets, and the order they appear in -- mirroring
rain.modules.assets.exporter's ad-hoc column picker. Tickets don't have
per-tenant custom fields the way assets do, so the column list is fixed
rather than pulled from the DB, but the shape (source/header/order) is
identical so the same export.html column-picker table and app.js wiring
work for both screens."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.xlsx_export import neutralize_formula
from rain.core.xlsx_export import render_xlsx as _render_xlsx
from rain.modules.tickets import service

BUILTIN_SOURCES = [
    ("ticket_number", "Ticket Number"),
    ("ticket_type", "Type"),
    ("title", "Title"),
    ("status", "Status"),
    ("severity", "Severity"),
    ("asset", "Asset"),
    ("description", "Description"),
    ("created_at", "Created"),
]


def available_columns() -> list[tuple[str, str]]:
    return BUILTIN_SOURCES


async def build_rows(
    db: AsyncSession, *, ticket_type: str | None, status: str | None, columns: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """columns: [{"source": "ticket_number" | ... | "created_at", "header": str}]"""
    tickets = await service.list_tickets(db, ticket_type=ticket_type, status=status)
    rows: list[dict[str, Any]] = []
    for t in tickets:
        row: dict[str, Any] = {}
        for col in columns:
            source, header = col["source"], col["header"]
            if source == "ticket_number":
                row[header] = t.ticket_number
            elif source == "ticket_type":
                row[header] = t.ticket_type
            elif source == "title":
                row[header] = t.title
            elif source == "status":
                row[header] = t.status
            elif source == "severity":
                row[header] = t.severity
            elif source == "asset":
                row[header] = t.asset.name if t.asset else None
            elif source == "description":
                row[header] = t.description
            elif source == "created_at":
                row[header] = t.created_at.isoformat() if t.created_at else None
            else:
                row[header] = None
        rows.append(row)
    return rows


def render_csv(rows: list[dict[str, Any]], headers: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({h: neutralize_formula(row.get(h)) for h in headers})
    return buf.getvalue()


def render_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2, default=str)


def render_xlsx(rows: list[dict[str, Any]], headers: list[str]) -> bytes:
    return _render_xlsx(rows, headers)
