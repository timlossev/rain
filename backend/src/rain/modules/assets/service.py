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


def _asset_list_stmt():
    return select(Asset).options(
        selectinload(Asset.asset_type),
        selectinload(Asset.field_values).selectinload(AssetFieldValue.field),
    )


async def list_assets(db: AsyncSession, *, asset_type_id: int | None = None) -> list[Asset]:
    stmt = _asset_list_stmt().order_by(Asset.name)
    if asset_type_id is not None:
        stmt = stmt.where(Asset.asset_type_id == asset_type_id)
    result = await db.execute(stmt)
    return list(result.scalars())


async def get_asset(db: AsyncSession, asset_id: int) -> Asset | None:
    stmt = _asset_list_stmt().where(Asset.id == asset_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def set_field_values(db: AsyncSession, asset: Asset, values: dict[int, Any]) -> None:
    existing = {fv.field_id: fv for fv in asset.field_values}
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
