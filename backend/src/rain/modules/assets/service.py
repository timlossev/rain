"""Query/mutation helpers for the asset registry. Kept thin and reusable
between the HTML router, importer, and exporter."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Sequence, Text, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import Asset, AssetFieldValue, AssetType, CustomField, ExportProfile

# "CI-000123" -- Configuration Item, the same 6-digit zero-padded scheme
# INC/VULN/CHG/DOC use (see rain.modules.tickets.service._next_ticket_number).
_CI_REF_RE = re.compile(r"^CI-(\d+)$", re.IGNORECASE)

# Single source of truth for the asset status vocabulary -- the manual
# create/edit form (assets/form.html) renders exactly this list as a
# <select>, so a manually-set asset can never carry anything else. CSV/JSON
# import (rain.modules.assets.importer) normalizes against this same tuple
# instead of writing whatever raw string a source system's export used
# verbatim -- see importer.py's commit_import for why that used to break
# the nav sidebar's "active" count silently.
ASSET_STATUSES = ("active", "in_repair", "retired", "decommissioned")


async def next_ci_number(db: AsyncSession) -> str:
    """Public (not the leading-underscore convention rain.modules.tickets.
    service._next_ticket_number and rain.modules.documents.service.
    _next_doc_number use) because, unlike those, asset creation happens in
    two different callers -- router.py's create_asset and importer.py's
    commit_import -- rather than a single create_asset() here."""
    seq = Sequence("ci_number_seq")
    next_val = await db.scalar(select(seq.next_value()))
    return f"CI-{next_val:06d}"


async def count_invalid_statuses(db: AsyncSession) -> int:
    """Assets whose status isn't one of ASSET_STATUSES -- can only exist
    from an import that predates importer.commit_import's normalization
    (or a re-import that hit the same bug -- see that function's comment).
    Used to conditionally show the "Fix imported statuses" action on the
    Assets list instead of always rendering a button that's a no-op."""
    return await db.scalar(select(func.count(Asset.id)).where(Asset.status.not_in(ASSET_STATUSES))) or 0


async def repair_invalid_statuses(db: AsyncSession) -> int:
    """Resets every asset whose status isn't one of ASSET_STATUSES to
    "active" -- the same fallback commit_import now applies going forward,
    exposed as a standalone action for rows an import file won't reach
    again (source data no longer at hand, external_id since changed, ...).
    Returns the number of rows fixed."""
    result = await db.execute(
        update(Asset).where(Asset.status.not_in(ASSET_STATUSES)).values(status="active")
    )
    await db.commit()
    return result.rowcount or 0


async def list_asset_types(db: AsyncSession, *, active_only: bool = False) -> list[AssetType]:
    stmt = select(AssetType).order_by(AssetType.sort_order, AssetType.name)
    if active_only:
        stmt = stmt.where(AssetType.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars())


async def get_asset_type(db: AsyncSession, asset_type_id: int) -> AssetType | None:
    return await db.get(AssetType, asset_type_id)


async def fields_for_type(db: AsyncSession, asset_type_id: int | None) -> list[CustomField]:
    stmt = (
        select(CustomField)
        .where(
            CustomField.scope == "asset",
            (CustomField.asset_type_id == asset_type_id) | (CustomField.asset_type_id.is_(None)),
        )
        .order_by(CustomField.sort_order, CustomField.label)
    )
    result = await db.execute(stmt)
    return list(result.scalars())


async def all_fields(db: AsyncSession) -> list[CustomField]:
    # scope == "asset": CustomField is now shared with ticket-scoped fields
    # (rain.modules.tickets.service.ticket_fields) -- without this filter
    # every asset screen using this (form field list, import mapping,
    # export column picker) would also list ticket custom fields.
    stmt = select(CustomField).where(CustomField.scope == "asset").order_by(CustomField.sort_order, CustomField.label)
    result = await db.execute(stmt)
    return list(result.scalars())


def asset_search_filter(q: str):
    """ILIKE partial ("contains") match against name/external_id/ci_number,
    plus a correlated EXISTS against AssetFieldValue for a hit anywhere in
    a custom field's value -- an asset's serial number, hostname, or any
    other EAV-stored field is just as often what someone actually typed as
    the asset's own name. AssetFieldValue.value is JSONB holding the raw
    scalar (not a keyed object), so it's cast to text rather than read via
    a `->>` key lookup; the cast's surrounding quotes/literal formatting
    (e.g. a string value casts to '"web-01"') don't affect a %contains%
    match. EXISTS (not a JOIN) so a hit on 2+ fields doesn't duplicate the
    asset row. Shared by the Assets list's `q` filter, the search-suggest
    autocomplete endpoint, and rain.modules.search.service's global search
    -- one definition of "matches this text" for all three."""
    pattern = f"%{q}%"
    field_match = (
        select(AssetFieldValue.id)
        .where(AssetFieldValue.asset_id == Asset.id, cast(AssetFieldValue.value, Text).ilike(pattern))
        .exists()
    )
    return or_(
        Asset.name.ilike(pattern),
        Asset.external_id.ilike(pattern),
        Asset.ci_number.ilike(pattern),
        field_match,
    )


# Column sort keys the Assets list's header links use (rain.modules.
# assets.router.list_assets / assets/list.html's sort_link macro, same
# shape as rain.modules.tickets.router's ticket list sorting). "type"
# isn't here -- it sorts by the related AssetType.name, which needs an
# explicit join (selectinload's second query can't drive an ORDER BY on
# the first), handled separately in asset_list_stmt below.
_SORT_COLUMNS = {
    "ci_number": Asset.ci_number,
    "name": Asset.name,
    "external_id": Asset.external_id,
    "status": Asset.status,
}


def asset_list_stmt(*, asset_type_id: int | None = None, q: str | None = None, sort: str | None = None, dir: str = "asc"):
    """Shared statement builder -- used both by list_assets() (full list,
    for exports/dropdowns/etc, where pagination would be wrong) and the
    Assets screen's paginated query (rain.modules.assets.router), so the
    two never drift apart on filtering/eager-load options."""
    stmt = select(Asset).options(
        selectinload(Asset.asset_type),
        selectinload(Asset.field_values).selectinload(AssetFieldValue.field),
    )
    if asset_type_id is not None:
        stmt = stmt.where(Asset.asset_type_id == asset_type_id)
    if q:
        stmt = stmt.where(asset_search_filter(q))
    if sort == "type":
        stmt = stmt.join(AssetType, Asset.asset_type_id == AssetType.id, isouter=True)
        order_col = AssetType.name
    else:
        order_col = _SORT_COLUMNS.get(sort, Asset.name)
    stmt = stmt.order_by(order_col.desc() if dir == "desc" else order_col.asc())
    return stmt


async def search_assets_brief(db: AsyncSession, q: str, *, limit: int = 8) -> list[Asset]:
    """Backs the Assets list's live autocomplete dropdown -- a short,
    unpaginated top-N, not the full filtered list asset_list_stmt builds
    for the table itself."""
    stmt = (
        select(Asset)
        .options(selectinload(Asset.asset_type))
        .where(asset_search_filter(q))
        .order_by(Asset.name)
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())


async def list_assets(db: AsyncSession, *, asset_type_id: int | None = None) -> list[Asset]:
    result = await db.execute(asset_list_stmt(asset_type_id=asset_type_id))
    return list(result.scalars())


async def get_asset(db: AsyncSession, asset_id: int) -> Asset | None:
    stmt = asset_list_stmt().where(Asset.id == asset_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_asset_by_ref(db: AsyncSession, ref: str) -> Asset | None:
    """`ref` is a ci_number ("CI-000123") -- the URL scheme asset detail
    links use -- or, for back-compat with any link/bookmark built before
    that switch, a bare integer id. Also tolerant of a missing or partial
    zero-pad ("CI-2" as well as "CI-000002"), same as
    rain.modules.tickets.service.get_ticket_by_ref."""
    ref = ref.strip()
    if ref.isdigit():
        asset = await get_asset(db, int(ref))
        if asset is not None:
            return asset
    match = _CI_REF_RE.match(ref)
    normalized = f"CI-{int(match.group(1)):06d}" if match else ref
    result = await db.execute(asset_list_stmt().where(Asset.ci_number == normalized))
    return result.scalar_one_or_none()


async def get_ci_numbers(db: AsyncSession, asset_ids: list[int]) -> dict[int, str]:
    """Bulk id -> ci_number lookup -- e.g. for rendering a polymorphic
    document link ("asset", linked_id) as CI-000123 instead of a bare
    database id, without eager-loading a full Asset per row. See
    rain.modules.tickets.service.get_ticket_numbers, same idea."""
    if not asset_ids:
        return {}
    result = await db.execute(select(Asset.id, Asset.ci_number).where(Asset.id.in_(asset_ids)))
    return {row.id: row.ci_number for row in result}


async def set_field_values(db: AsyncSession, asset: Asset, values: dict[int, Any]) -> None:
    # Queried explicitly rather than via `asset.field_values` -- that's a
    # lazy relationship, and plain attribute access on it isn't safe under
    # AsyncSession unless it's already been eagerly loaded (get_asset()
    # does via selectinload; a just-constructed Asset in the create path
    # hasn't been, and touching it raised sqlalchemy.exc.MissingGreenlet:
    # "greenlet_spawn has not been called" -- confirmed against a real
    # request, traceback returned inline via DEBUG=true).
    result = await db.execute(select(AssetFieldValue).where(AssetFieldValue.asset_id == asset.id))
    existing = {fv.field_id: fv for fv in result.scalars()}
    for field_id, value in values.items():
        if field_id in existing:
            existing[field_id].value = value
        else:
            db.add(AssetFieldValue(asset_id=asset.id, field_id=field_id, value=value))


async def list_export_profiles(db: AsyncSession) -> list[ExportProfile]:
    result = await db.execute(
        select(ExportProfile).where(ExportProfile.scope == "asset").order_by(ExportProfile.name)
    )
    return list(result.scalars())


async def save_export_profile(
    db: AsyncSession,
    *,
    name: str,
    asset_type_id: int | None,
    fmt: str,
    columns: list[dict],
    actor_id: int,
) -> ExportProfile:
    profile = ExportProfile(
        name=name, scope="asset", asset_type_id=asset_type_id, format=fmt, columns=columns, created_by=actor_id
    )
    db.add(profile)
    await db.commit()
    return profile
