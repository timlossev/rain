"""Runs a saved ExportRecipe: fan out to each step's own ExportProfile
export, optionally jq-filtering each step's rows on its own, then
optionally running one more "assembly" filter over the collected
{label: value} dict to produce one final document.

This exists because a single ExportProfile's own jq_document_id can
only ever reshape *that one export* -- it has no way to pull in a
second, independently-scoped export (a different asset type, or a
ticket export alongside an asset one) to build something like an OSCAL
System Security Plan, which needs system-characteristics + components +
control-implementation sections from three different sources. A recipe
is the fan-out-then-merge answer: run each source's own export
separately, then combine.

No HTTP request/form in play here, same reasoning as rain.modules.
calendar.export_runner.run_saved_export_profile (which this doesn't
reuse directly: that one always renders to profile.format's own text,
whereas every step here needs the *parsed* row value so it can be
nested into the collected dict, and a step's own filter_document_id
needs to be able to override the profile's own jq_document_id rather
than stack with it)."""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.jq_transform import apply_jq_filter_value
from rain.db.tenant_models import ExportRecipe, ExportRecipeStep
from rain.modules.assets import exporter as asset_exporter
from rain.modules.documents import service as document_service
from rain.modules.tickets import exporter as ticket_exporter


async def _run_step(db: AsyncSession, step: ExportRecipeStep) -> object:
    profile = step.export_profile
    if profile.scope == "ticket":
        rows = await ticket_exporter.build_rows(db, ticket_type=None, status=None, columns=profile.columns)
    else:
        rows = await asset_exporter.build_rows(db, asset_type_id=profile.asset_type_id, columns=profile.columns)

    # The step's own filter overrides the profile's saved one for this
    # recipe's purposes, rather than stacking with it -- see the
    # module's own docstring for why.
    filter_document_id = step.filter_document_id or profile.jq_document_id
    if filter_document_id is None:
        return rows
    filter_text = await document_service.get_document_text_body(db, filter_document_id)
    return apply_jq_filter_value(rows, filter_text) if filter_text else rows


async def run_export_recipe(db: AsyncSession, recipe: ExportRecipe) -> str:
    step_outputs = {step.label: await _run_step(db, step) for step in recipe.steps}

    final_value: object = step_outputs
    if recipe.assembly_filter_document_id:
        assembly_text = await document_service.get_document_text_body(db, recipe.assembly_filter_document_id)
        if assembly_text:
            final_value = apply_jq_filter_value(step_outputs, assembly_text)

    return json.dumps(final_value, indent=2, default=str)
