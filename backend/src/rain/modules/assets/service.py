"""Query/mutation helpers for the asset registry. Kept thin and reusable
between the HTML router, importer, and exporter."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import Asset, AssetFieldValue, AssetType, CustomField, ExportProfile


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
        .where((CustomField.asset_type_id == asset_type_id) | (CustomField.asset_type_id.is_(None)))
        .order_by(CustomField.sort_order, CustomField.label)
    )
    result = await db.execute(stmt)
    return list(result.scalars())


async def all_fields(db: AsyncSession) -> list[CustomField]:
    result = await db.execute(select(CustomField).order_by(CustomField.sort_order, CustomField.label))
    return list(result.scalars())


def asset_list_stmt(*, asset_type_id: int | None = None):
    """Shared statement builder -- used both by list_assets() (full list,
    for exports/dropdowns/etc, where pagination would be wrong) and the
    Assets screen's paginated query (rain.modules.assets.router), so the
    two never drift apart on filtering/eager-load options."""
    stmt = select(Asset).options(
        selectinload(Asset.asset_type),
        selectinload(Asset.field_values).selectinload(AssetFieldValue.field),
    ).order_by(Asset.name)
    if asset_type_id is not None:
        stmt = stmt.where(Asset.asset_type_id == asset_type_id)
    return stmt


async def list_assets(db: AsyncSession, *, asset_type_id: int | None = None) -> list[Asset]:
    result = await db.execute(asset_list_stmt(asset_type_id=asset_type_id))
    return list(result.scalars())


async def get_asset(db: AsyncSession, asset_id: int) -> Asset | None:
    stmt = _asset_list_stmt().where(Asset.id == asset_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


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
    result = await db.execute(select(ExportProfile).order_by(ExportProfile.name))
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
    profile = ExportProfile(name=name, asset_type_id=asset_type_id, format=fmt, columns=columns, created_by=actor_id)
    db.add(profile)
    await db.commit()
    return profile
