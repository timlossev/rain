"""Shared .xlsx rendering for the CSV/JSON/Excel export screens (Assets,
Tickets). openpyxl is pure Python -- no compiled extension/system library,
consistent with this app's policy of nothing extra to build into the
container image."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import Workbook

_SCALAR_TYPES = (str, int, float, bool, type(None))

# Excel/LibreOffice/Sheets treat a cell whose text starts with any of
# these as a formula to evaluate on open, not literal data -- CSV/XLSX
# export is the one place row data (a ticket title, an asset field
# value, ...) reaches a spreadsheet program instead of just this app's
# own autoescaped pages, so a value an anonymous portal visitor or any
# tenant user supplied can otherwise run arbitrary formulas (including
# ones that reach out to a URL) on whoever opens the export. Prefixing
# with a bare apostrophe is the standard mitigation (same one GitHub/
# Google Sheets exports use): every spreadsheet program treats that as
# "the rest of this cell is text," at the cost of the apostrophe itself
# staying visible in the cell -- CSV has no header flag to hide it the
# way manually typing one into a spreadsheet does.
_FORMULA_TRIGGER_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize_formula(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_PREFIXES):
        return "'" + value
    return value


def render_xlsx(rows: list[dict[str, Any]], headers: list[str]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(
            [neutralize_formula(value if isinstance((value := row.get(h)), _SCALAR_TYPES) else str(value)) for h in headers]
        )
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
