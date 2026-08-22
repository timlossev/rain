"""CSV/JSON export with a caller-supplied column set: which fields, what
header each one gets, and the order they appear in -- either ad hoc or
loaded from a saved rain.db.tenant_models.ExportProfile."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.xlsx_export import neutralize_formula
from rain.core.xlsx_export import render_xlsx as _render_xlsx
from rain.modules.assets import service

BUILTIN_SOURCES = [
    ("ci_number", "CI Number"),
    ("name", "Name"),
    ("external_id", "External ID"),
    ("status", "Status"),
    ("asset_type", "Asset Type"),
]


async def available_columns(db: AsyncSession, asset_type_id: int | None) -> list[tuple[str, str]]:
    fields = await (service.fields_for_type(db, asset_type_id) if asset_type_id else service.all_fields(db))
    return BUILTIN_SOURCES + [(f"field_{f.id}", f.label) for f in fields]


async def build_rows(
    db: AsyncSession, *, asset_type_id: int | None, columns: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """columns: [{"source": "name" | "external_id" | "status" | "asset_type" | "field_<id>", "header": str}]"""
    assets = await service.list_assets(db, asset_type_id=asset_type_id)
    rows: list[dict[str, Any]] = []
    for asset in assets:
        value_by_field = {fv.field_id: fv.value for fv in asset.field_values}
        row: dict[str, Any] = {}
        for col in columns:
            source, header = col["source"], col["header"]
            if source == "name":
                row[header] = asset.name
            elif source == "external_id":
                row[header] = asset.external_id
            elif source == "status":
                row[header] = asset.status
            elif source == "asset_type":
                row[header] = asset.asset_type.name if asset.asset_type else None
            elif source.startswith("field_"):
                row[header] = value_by_field.get(int(source.split("_", 1)[1]))
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
