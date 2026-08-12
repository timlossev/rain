"""Shared .xlsx rendering for the CSV/JSON/Excel export screens (Assets,
Tickets). openpyxl is pure Python -- no compiled extension/system library,
consistent with this app's policy of nothing extra to build into the
container image."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import Workbook

_SCALAR_TYPES = (str, int, float, bool, type(None))


def render_xlsx(rows: list[dict[str, Any]], headers: list[str]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append([value if isinstance((value := row.get(h)), _SCALAR_TYPES) else str(value) for h in headers])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
