"""CRUD for rain.db.tenant_models.ExportRecipe/ExportRecipeStep -- see
rain.core.export_recipe for actually running one."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import AssetType, ExportProfile, ExportRecipe, ExportRecipeStep


def _recipe_stmt():
    return select(ExportRecipe).options(selectinload(ExportRecipe.steps)).order_by(ExportRecipe.name)


async def list_recipes(db: AsyncSession) -> list[ExportRecipe]:
    result = await db.execute(_recipe_stmt())
    return list(result.scalars())


async def get_recipe(db: AsyncSession, recipe_id: int) -> ExportRecipe | None:
    return await db.get(
        ExportRecipe,
        recipe_id,
        options=[selectinload(ExportRecipe.steps).selectinload(ExportRecipeStep.export_profile)],
    )


async def list_all_export_profiles(db: AsyncSession) -> list[dict[str, Any]]:
    """Every saved profile, ticket- and asset-scoped alike -- a recipe
    step can be either, unlike the plain export screens (each of which
    only ever lists its own scope's profiles). Each entry carries a
    group_label ("Tickets", or the targeted asset type's own name)
    instead of the bare scope string, so the step picker's <optgroup>
    can tell the user what a profile actually runs against -- a
    profile's own name (e.g. "OSCAL - Certification Package") doesn't
    say that on its own."""
    result = await db.execute(select(ExportProfile).order_by(ExportProfile.scope, ExportProfile.name))
    profiles = list(result.scalars())
    asset_type_ids = {p.asset_type_id for p in profiles if p.asset_type_id}
    asset_type_name_by_id: dict[int, str] = {}
    if asset_type_ids:
        rows = await db.execute(select(AssetType.id, AssetType.name).where(AssetType.id.in_(asset_type_ids)))
        asset_type_name_by_id = dict(rows.all())
    out = []
    for p in profiles:
        if p.scope == "ticket":
            group_label = "Tickets"
        elif p.asset_type_id:
            group_label = asset_type_name_by_id.get(p.asset_type_id, "Assets (deleted type)")
        else:
            group_label = "Assets (all types)"
        out.append({"id": p.id, "name": p.name, "group_label": group_label})
    out.sort(key=lambda p: (p["group_label"], p["name"]))
    return out


async def create_recipe(
    db: AsyncSession,
    *,
    name: str,
    steps: list[dict[str, Any]],
    assembly_filter_document_id: int | None,
    actor_id: int,
    save_to_document: bool = False,
    destination_document_id: int | None = None,
    destination_title: str | None = None,
    destination_is_shareable: bool = False,
) -> ExportRecipe:
    recipe = ExportRecipe(
        name=name,
        assembly_filter_document_id=assembly_filter_document_id,
        save_to_document=save_to_document,
        destination_document_id=destination_document_id,
        destination_title=destination_title,
        destination_is_shareable=destination_is_shareable,
        created_by=actor_id,
        steps=[
            ExportRecipeStep(
                step_order=i,
                label=s["label"],
                export_profile_id=s["export_profile_id"],
                filter_document_id=s["filter_document_id"],
            )
            for i, s in enumerate(steps)
        ],
    )
    db.add(recipe)
    await db.commit()
    return recipe


async def update_recipe(
    db: AsyncSession,
    recipe: ExportRecipe,
    *,
    name: str,
    steps: list[dict[str, Any]],
    assembly_filter_document_id: int | None,
    save_to_document: bool = False,
    destination_document_id: int | None = None,
    destination_title: str | None = None,
    destination_is_shareable: bool = False,
) -> None:
    """Steps have no identity worth preserving across an edit (just an
    ordered label/profile/filter list) -- same reasoning as Approval
    Flow's own _replace_approval_steps, so this rebuilds them from
    scratch rather than diffing against what's already there.
    Reassigning the whole collection relies on steps' own
    cascade="all, delete-orphan" to actually delete the old rows."""
    recipe.name = name
    recipe.assembly_filter_document_id = assembly_filter_document_id
    recipe.save_to_document = save_to_document
    recipe.destination_document_id = destination_document_id
    recipe.destination_title = destination_title
    recipe.destination_is_shareable = destination_is_shareable
    recipe.steps = [
        ExportRecipeStep(
            step_order=i,
            label=s["label"],
            export_profile_id=s["export_profile_id"],
            filter_document_id=s["filter_document_id"],
        )
        for i, s in enumerate(steps)
    ]
    await db.commit()


async def delete_recipe(db: AsyncSession, recipe: ExportRecipe) -> None:
    await db.delete(recipe)
    await db.commit()
