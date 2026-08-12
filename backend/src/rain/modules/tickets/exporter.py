"""Fixed-column CSV/JSON ticket export. Tickets don't carry custom fields
the way assets do, so unlike rain.modules.assets.exporter this doesn't need
a configurable column picker -- just a type/status filter and a format."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from rain.modules.tickets import service

COLUMNS = ["ticket_number", "ticket_type", "title", "status", "severity", "asset", "created_at"]


async def build_rows(db: AsyncSession, *, ticket_type: str | None, status: str | None) -> list[dict[str, Any]]:
    tickets = await service.list_tickets(db, ticket_type=ticket_type, status=status)
    return [
        {
            "ticket_number": t.ticket_number,
            "ticket_type": t.ticket_type,
            "title": t.title,
            "status": t.status,
            "severity": t.severity,
            "asset": t.asset.name if t.asset else "",
            "created_at": t.created_at.isoformat() if t.created_at else "",
        }
        for t in tickets
    ]


def render_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def render_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2, default=str)
