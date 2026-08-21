"""CSV/JSON import: parse -> user maps columns to fields (auto-suggested by
header name) -> commit, upserting by external_id when present."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field as dc_field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import Asset
from rain.modules.assets import service
from rain.modules.assets.schemas import coerce_field_value


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
    updated: int = 0
    errors: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)


async def commit_import(
    db: AsyncSession,
    *,
    asset_type_id: int,
    rows: list[dict[str, Any]],
    mapping: dict[str, str],
    actor_id: int,
) -> ImportResult:
    """mapping: target ("name" | "external_id" | "status" | "field_<id>") -> source column name."""
    result = ImportResult()
    fields_by_id = {f.id: f for f in await service.fields_for_type(db, asset_type_id)}

    for i, row in enumerate(rows, start=1):
        try:
            name_col = mapping.get("name")
            name = str(row.get(name_col, "")).strip() if name_col else ""
            if not name:
                result.errors.append(f"row {i}: missing name")
                continue

            ext_col = mapping.get("external_id")
            external_id = str(row.get(ext_col, "")).strip() or None if ext_col else None

            asset = None
            if external_id:
                existing = await db.execute(
                    select(Asset).where(Asset.external_id == external_id, Asset.asset_type_id == asset_type_id)
                )
                asset = existing.scalar_one_or_none()

            if asset is None:
                asset = Asset(
                    ci_number=await service.next_ci_number(db),
                    asset_type_id=asset_type_id,
                    name=name,
                    external_id=external_id,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                db.add(asset)
                await db.flush()
                result.created += 1
            else:
                asset.name = name
                asset.updated_by = actor_id
                result.updated += 1

            status_col = mapping.get("status")
            if status_col and row.get(status_col):
                # Normalized (casefolded, whitespace/hyphens collapsed to
                # "_") against service.ASSET_STATUSES rather than written
                # verbatim -- a source system's own export vocabulary
                # ("Active", "In Service", "1", ...) previously landed in
                # the DB unchanged, which the manual edit form's <select>
                # can never produce and which the nav sidebar's "active"
                # count (an exact-string match) silently didn't count at
                # all. Anything that doesn't map cleanly is left at the
                # asset's existing/default status and reported back so the
                # import summary shows it instead of hiding it.
                raw_status = str(row[status_col]).strip()
                normalized = raw_status.lower().replace("-", "_").replace(" ", "_")
                if normalized in service.ASSET_STATUSES:
                    asset.status = normalized
                else:
                    result.warnings.append(
                        f"row {i}: unrecognized status '{raw_status}' -- kept as '{asset.status}'"
                    )

            values: dict[int, Any] = {}
            for field_id, field_def in fields_by_id.items():
                col = mapping.get(f"field_{field_id}")
                if col and col in row:
                    values[field_id] = coerce_field_value(field_def.field_type, row.get(col))
            if values:
                await service.set_field_values(db, asset, values)

        except Exception as exc:  # one bad row shouldn't abort the whole import
            result.errors.append(f"row {i}: {exc}")

    await db.commit()
    return result
