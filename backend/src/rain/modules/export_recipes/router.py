"""Export Recipes: a named, ordered list of steps (each an existing
ExportProfile, optionally with its own jq filter) plus one optional
assembly filter run over the collected results -- see rain.core.
export_recipe's own module docstring for why this exists (a single
profile's jq_document_id can only reshape its own export; a recipe
fans out to several and merges them). require_login, same access
level as the plain Tickets/Assets export screens this builds on, not
admin-gated -- a recipe only ever runs exports its own author could
already run by hand, one at a time.

The step-count UI follows rain.modules.admin.router's own Approval
Flow form exactly: _MAX_RECIPE_STEPS rows are always rendered server-
side, app.js's existing [data-step-field] handler show/hides them, and
a row with no profile picked is simply skipped on submit -- no new JS
needed."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.export_recipe import run_export_recipe
from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.modules.documents import service as document_service
from rain.modules.export_recipes import service
from rain.web.nav import build_nav_context
from rain.web.templating import templates

router = APIRouter(prefix="/export-recipes", tags=["Export Recipes"])

# Comfortably more than the ~4 steps a full OSCAL SSP assembly needs
# (system-characteristics, components, control-implementation, back-
# matter) without inviting an unreadably long form.
_MAX_RECIPE_STEPS = 8


@router.get("", response_class=HTMLResponse)
async def recipes_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    recipes = await service.list_recipes(tenant_db)
    return templates.TemplateResponse(
        request, "export_recipes/list.html", {**nav, "ctx": ctx, "recipes": recipes}
    )


async def _form_context(
    tenant_db: AsyncSession,
    ctx: RequestContext,
    *,
    recipe,
    error: str | None = None,
) -> dict:
    nav = await build_nav_context(ctx)
    profiles = await service.list_all_export_profiles(tenant_db)

    # Keyed by slot position (1-based), same convention Approval Flow's
    # own step_prefill uses -- the form's step_range loop reads row i
    # from step_prefill.get(i).
    step_prefill: dict[int, dict] = {}
    if recipe is not None:
        for i, step in enumerate(recipe.steps, start=1):
            filter_doc = (
                await document_service.get_document(tenant_db, step.filter_document_id)
                if step.filter_document_id
                else None
            )
            step_prefill[i] = {
                "label": step.label,
                "export_profile_id": step.export_profile_id,
                "filter_document_id": step.filter_document_id,
                "filter_document_label": f"{filter_doc.doc_number}: {filter_doc.title}" if filter_doc else "",
            }

    assembly_doc = (
        await document_service.get_document(tenant_db, recipe.assembly_filter_document_id)
        if recipe is not None and recipe.assembly_filter_document_id
        else None
    )
    destination_doc = (
        await document_service.get_document(tenant_db, recipe.destination_document_id)
        if recipe is not None and recipe.destination_document_id
        else None
    )

    return {
        **nav,
        "ctx": ctx,
        "recipe": recipe,
        "profiles": profiles,
        "step_range": range(1, _MAX_RECIPE_STEPS + 1),
        "step_prefill": step_prefill,
        "selected_assembly_filter_document_id": recipe.assembly_filter_document_id if recipe else None,
        "selected_assembly_filter_document_label": f"{assembly_doc.doc_number}: {assembly_doc.title}" if assembly_doc else "",
        "selected_save_to_document": recipe.save_to_document if recipe else False,
        "selected_destination_document_id": recipe.destination_document_id if recipe else None,
        "selected_destination_document_label": f"{destination_doc.doc_number}: {destination_doc.title}" if destination_doc else "",
        "selected_destination_title": (recipe.destination_title or "") if recipe else "",
        "selected_destination_is_shareable": recipe.destination_is_shareable if recipe else False,
        "error": error,
    }


@router.get("/new", response_class=HTMLResponse)
async def recipe_new_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    context = await _form_context(tenant_db, ctx, recipe=None)
    return templates.TemplateResponse(request, "export_recipes/form.html", context)


def _collect_steps(form) -> list[dict]:
    """Shared by create/update -- a slot with no profile picked is
    skipped, same "blank row = no step" convention Approval Flow's own
    _replace_approval_steps uses."""
    steps = []
    for i in range(1, _MAX_RECIPE_STEPS + 1):
        profile_id = str(form.get(f"step_profile_{i}", "")).strip()
        if not profile_id:
            continue
        label = str(form.get(f"step_label_{i}", "")).strip() or f"step{len(steps) + 1}"
        filter_document_id = str(form.get(f"step_filter_{i}", "")).strip()
        steps.append(
            {
                "label": label,
                "export_profile_id": int(profile_id),
                "filter_document_id": int(filter_document_id) if filter_document_id else None,
            }
        )
    return steps


@router.post("")
async def recipe_create(
    request: Request,
    name: str = Form(...),
    assembly_filter_document_id: str = Form(""),
    destination_mode: str = Form("download"),
    destination_document_id: str = Form(""),
    destination_title: str = Form(""),
    destination_is_shareable: bool = Form(False),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    steps = _collect_steps(form)
    if not steps:
        context = await _form_context(tenant_db, ctx, recipe=None, error="A recipe needs at least one step.")
        return templates.TemplateResponse(request, "export_recipes/form.html", context, status_code=400)
    await service.create_recipe(
        tenant_db,
        name=name.strip(),
        steps=steps,
        assembly_filter_document_id=int(assembly_filter_document_id) if assembly_filter_document_id.strip() else None,
        actor_id=ctx.user.id,
        save_to_document=destination_mode == "save_to_document",
        destination_document_id=int(destination_document_id) if destination_document_id.strip() else None,
        destination_title=destination_title.strip() or None,
        destination_is_shareable=destination_is_shareable,
    )
    return RedirectResponse("/export-recipes", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{recipe_id:int}/edit", response_class=HTMLResponse)
async def recipe_edit_form(
    request: Request,
    recipe_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    recipe = await service.get_recipe(tenant_db, recipe_id)
    if recipe is None:
        return RedirectResponse("/export-recipes", status_code=status.HTTP_303_SEE_OTHER)
    context = await _form_context(tenant_db, ctx, recipe=recipe)
    return templates.TemplateResponse(request, "export_recipes/form.html", context)


@router.post("/{recipe_id:int}/edit")
async def recipe_update(
    request: Request,
    recipe_id: int,
    name: str = Form(...),
    assembly_filter_document_id: str = Form(""),
    destination_mode: str = Form("download"),
    destination_document_id: str = Form(""),
    destination_title: str = Form(""),
    destination_is_shareable: bool = Form(False),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    recipe = await service.get_recipe(tenant_db, recipe_id)
    if recipe is None:
        return RedirectResponse("/export-recipes", status_code=status.HTTP_303_SEE_OTHER)
    form = await request.form()
    steps = _collect_steps(form)
    if not steps:
        context = await _form_context(tenant_db, ctx, recipe=recipe, error="A recipe needs at least one step.")
        return templates.TemplateResponse(request, "export_recipes/form.html", context, status_code=400)
    await service.update_recipe(
        tenant_db,
        recipe,
        name=name.strip(),
        steps=steps,
        assembly_filter_document_id=int(assembly_filter_document_id) if assembly_filter_document_id.strip() else None,
        save_to_document=destination_mode == "save_to_document",
        destination_document_id=int(destination_document_id) if destination_document_id.strip() else None,
        destination_title=destination_title.strip() or None,
        destination_is_shareable=destination_is_shareable,
    )
    return RedirectResponse("/export-recipes", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{recipe_id:int}/delete")
async def recipe_delete(
    recipe_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    recipe = await service.get_recipe(tenant_db, recipe_id)
    if recipe is not None:
        await service.delete_recipe(tenant_db, recipe)
    return RedirectResponse("/export-recipes", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{recipe_id:int}/run")
async def recipe_run(
    recipe_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    recipe = await service.get_recipe(tenant_db, recipe_id)
    if recipe is None:
        return RedirectResponse("/export-recipes", status_code=status.HTTP_303_SEE_OTHER)
    body = await run_export_recipe(tenant_db, recipe)

    if recipe.save_to_document:
        if recipe.destination_document_id:
            doc = await document_service.get_document(tenant_db, recipe.destination_document_id)
            if doc is None:
                return RedirectResponse(
                    f"/export-recipes/{recipe.id}/edit?error=The+document+picked+to+overwrite+no+longer+exists.",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
            await document_service.update_body(tenant_db, doc, body)
        else:
            doc = await document_service.create_document_from_bytes(
                tenant_db,
                tenant_schema=ctx.active_tenant.schema_name,
                title=recipe.destination_title or recipe.name,
                filename=f"{recipe.name}.json",
                mime_type="application/json",
                data=body.encode("utf-8"),
                actor_id=ctx.user.id,
            )
        if recipe.destination_is_shareable:
            await document_service.update_sharing(tenant_db, doc, True)
        return RedirectResponse(f"/documents/{doc.doc_number}?ok=1", status_code=status.HTTP_303_SEE_OTHER)

    slug = "".join(c if c.isalnum() else "-" for c in recipe.name.lower()).strip("-") or "export-recipe"
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{slug}.json"'},
    )
