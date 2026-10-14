"""CRUD for rain.db.tenant_models.ExportRecipe/ExportRecipeStep -- see
rain.core.export_recipe for actually running one."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import ExportProfile, ExportRecipe, ExportRecipeStep


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


async def list_all_export_profiles(db: AsyncSession) -> list[ExportProfile]:
    """Every saved profile, ticket- and asset-scoped alike -- a recipe
    step can be either, unlike the plain export screens (each of which
    only ever lists its own scope's profiles). Ordered by scope so the
    step picker's <option> groups land together."""
    result = await db.execute(select(ExportProfile).order_by(ExportProfile.scope, ExportProfile.name))
    return list(result.scalars())


async def create_recipe(
    db: AsyncSession, *, name: str, steps: list[dict[str, Any]], assembly_filter_document_id: int | None, actor_id: int
) -> ExportRecipe:
    recipe = ExportRecipe(
        name=name,
        assembly_filter_document_id=assembly_filter_document_id,
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
) -> None:
    """Steps have no identity worth preserving across an edit (just an
    ordered label/profile/filter list) -- same reasoning as Approval
    Flow's own _replace_approval_steps, so this rebuilds them from
    scratch rather than diffing against what's already there.
    Reassigning the whole collection relies on steps' own
    cascade="all, delete-orphan" to actually delete the old rows."""
    recipe.name = name
    recipe.assembly_filter_document_id = assembly_filter_document_id
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
