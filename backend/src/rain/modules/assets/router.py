from __future__ import annotations

import io
import secrets

from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.rbac import require_login
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context, get_tenant_db
from rain.db.tenant_models import Asset, AssetType, CustomField
from rain.modules.assets import exporter, importer, service, sync as sync_service
from rain.modules.assets.schemas import coerce_field_value
from rain.web.nav import build_nav_context
from rain.web.templating import templates
from rain.web.uploads import import_stash_path

router = APIRouter(prefix="/assets")


# ---------------------------------------------------------------- assets --


@router.get("", response_class=HTMLResponse)
async def list_assets(
    request: Request,
    asset_type_id: int | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    assets = await service.list_assets(tenant_db, asset_type_id=asset_type_id)
    asset_types = await service.list_asset_types(tenant_db)
    return templates.TemplateResponse(
        request,
        "assets/list.html",
        {**nav, "ctx": ctx, "assets": assets, "asset_types": asset_types, "selected_type": asset_type_id},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_asset_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    asset_types = await service.list_asset_types(tenant_db, active_only=True)
    fields = await service.fields_for_type(tenant_db, asset_types[0].id) if asset_types else []
    return templates.TemplateResponse(
        request,
        "assets/form.html",
        {**nav, "ctx": ctx, "asset": None, "asset_types": asset_types, "fields": fields, "values": {}, "error": None},
    )


@router.get("/fields-for-type/{asset_type_id}", response_class=HTMLResponse)
async def fields_for_type_fragment(
    request: Request,
    asset_type_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    fields = await service.fields_for_type(tenant_db, asset_type_id)
    return templates.TemplateResponse(request, "assets/_fields_fragment.html", {"fields": fields, "values": {}})


@router.post("")
async def create_asset(
    request: Request,
    name: str = Form(...),
    asset_type_id: int = Form(...),
    external_id: str = Form(""),
    asset_status: str = Form("active", alias="status"),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    asset = Asset(
        name=name.strip(),
        asset_type_id=asset_type_id,
        external_id=external_id.strip() or None,
        status=asset_status,
        created_by=ctx.user.id,
        updated_by=ctx.user.id,
    )
    tenant_db.add(asset)
    await tenant_db.flush()

    fields = await service.fields_for_type(tenant_db, asset_type_id)
    values = {}
    for f in fields:
        raw = form.get(f"field_{f.id}")
        values[f.id] = coerce_field_value(f.field_type, raw if isinstance(raw, str) else None)
    await service.set_field_values(tenant_db, asset, values)

    await tenant_db.commit()
    return RedirectResponse("/assets", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{asset_id}/edit", response_class=HTMLResponse)
async def edit_asset_form(
    request: Request,
    asset_id: int,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    asset = await service.get_asset(tenant_db, asset_id)
    if asset is None:
        return RedirectResponse("/assets", status_code=status.HTTP_303_SEE_OTHER)
    asset_types = await service.list_asset_types(tenant_db)
    fields = await service.fields_for_type(tenant_db, asset.asset_type_id)
    values = {fv.field_id: fv.value for fv in asset.field_values}
    return templates.TemplateResponse(
        request,
        "assets/form.html",
        {**nav, "ctx": ctx, "asset": asset, "asset_types": asset_types, "fields": fields, "values": values, "error": None},
    )


@router.post("/{asset_id}")
async def update_asset(
    request: Request,
    asset_id: int,
    name: str = Form(...),
    asset_type_id: int = Form(...),
    external_id: str = Form(""),
    asset_status: str = Form("active", alias="status"),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    asset = await service.get_asset(tenant_db, asset_id)
    if asset is None:
        return RedirectResponse("/assets", status_code=status.HTTP_303_SEE_OTHER)

    asset.name = name.strip()
    asset.asset_type_id = asset_type_id
    asset.external_id = external_id.strip() or None
    asset.status = asset_status
    asset.updated_by = ctx.user.id

    fields = await service.fields_for_type(tenant_db, asset_type_id)
    values = {}
    for f in fields:
        raw = form.get(f"field_{f.id}")
        values[f.id] = coerce_field_value(f.field_type, raw if isinstance(raw, str) else None)
    await service.set_field_values(tenant_db, asset, values)

    await tenant_db.commit()
    return RedirectResponse("/assets", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{asset_id}/delete")
async def delete_asset(
    asset_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    asset = await tenant_db.get(Asset, asset_id)
    if asset is not None:
        await tenant_db.delete(asset)
        await tenant_db.commit()
    return RedirectResponse("/assets", status_code=status.HTTP_303_SEE_OTHER)


# ------------------------------------------------------- types & fields --


@router.get("/types", response_class=HTMLResponse)
async def types_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    asset_types = await service.list_asset_types(tenant_db)
    fields_by_type: dict[int | None, list] = {}
    for f in await service.all_fields(tenant_db):
        fields_by_type.setdefault(f.asset_type_id, []).append(f)
    return templates.TemplateResponse(
        request,
        "assets/types.html",
        {**nav, "ctx": ctx, "asset_types": asset_types, "fields_by_type": fields_by_type, "error": None},
    )


@router.post("/types")
async def create_type(
    key: str = Form(...),
    name: str = Form(...),
    icon: str = Form(""),
    description: str = Form(""),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    tenant_db.add(AssetType(key=key.strip().lower(), name=name.strip(), icon=icon.strip() or None, description=description.strip() or None))
    await tenant_db.commit()
    return RedirectResponse("/assets/types", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/types/{asset_type_id}/delete")
async def delete_type(
    asset_type_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    asset_type = await tenant_db.get(AssetType, asset_type_id)
    if asset_type is not None:
        await tenant_db.delete(asset_type)
        await tenant_db.commit()
    return RedirectResponse("/assets/types", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/fields")
async def create_field(
    asset_type_id: str = Form(""),
    field_key: str = Form(...),
    label: str = Form(...),
    field_type: str = Form("text"),
    select_options: str = Form(""),
    is_required: bool = Form(False),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    options = [o.strip() for o in select_options.split(",") if o.strip()] if field_type == "select" else None
    tenant_db.add(
        CustomField(
            asset_type_id=int(asset_type_id) if asset_type_id else None,
            field_key=field_key.strip().lower(),
            label=label.strip(),
            field_type=field_type,
            select_options=options,
            is_required=is_required,
        )
    )
    await tenant_db.commit()
    return RedirectResponse("/assets/types", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/fields/{field_id}/delete")
async def delete_field(
    field_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    field = await tenant_db.get(CustomField, field_id)
    if field is not None:
        await tenant_db.delete(field)
        await tenant_db.commit()
    return RedirectResponse("/assets/types", status_code=status.HTTP_303_SEE_OTHER)


# ------------------------------------------------------------- export ----


@router.get("/export", response_class=HTMLResponse)
async def export_form(
    request: Request,
    asset_type_id: int | None = None,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    asset_types = await service.list_asset_types(tenant_db)
    columns = await exporter.available_columns(tenant_db, asset_type_id)
    profiles = await service.list_export_profiles(tenant_db)
    return templates.TemplateResponse(
        request,
        "assets/export.html",
        {**nav, "ctx": ctx, "asset_types": asset_types, "columns": columns, "profiles": profiles, "selected_type": asset_type_id},
    )


@router.post("/export")
async def export_run(
    request: Request,
    asset_type_id: str = Form(""),
    fmt: str = Form("csv"),
    save_as: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    columns = []
    for key in form.keys():
        if key.startswith("use_"):
            source = key[len("use_") :]
            header = str(form.get(f"header_{source}", source)).strip() or source
            columns.append({"source": source, "header": header, "order": int(form.get(f"order_{source}", 0) or 0)})
    columns.sort(key=lambda c: c["order"])

    type_id = int(asset_type_id) if asset_type_id else None
    rows = await exporter.build_rows(tenant_db, asset_type_id=type_id, columns=columns)

    if save_as.strip():
        await service.save_export_profile(
            tenant_db, name=save_as.strip(), asset_type_id=type_id, fmt=fmt, columns=columns, actor_id=ctx.user.id
        )

    if fmt == "json":
        content, media_type, filename = exporter.render_json(rows), "application/json", "assets-export.json"
    else:
        headers = [c["header"] for c in columns]
        content, media_type, filename = exporter.render_csv(rows, headers), "text/csv", "assets-export.csv"

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------------------------------------- import ----


@router.get("/import", response_class=HTMLResponse)
async def import_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    asset_types = await service.list_asset_types(tenant_db, active_only=True)
    return templates.TemplateResponse(request, "assets/import.html", {**nav, "ctx": ctx, "asset_types": asset_types})


@router.post("/import/preview", response_class=HTMLResponse)
async def import_preview(
    request: Request,
    file: UploadFile,
    asset_type_id: int = Form(...),
    fmt: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    raw = await file.read()
    token = secrets.token_hex(16)
    import_stash_path(token).write_bytes(raw)

    headers = importer.sniff_headers(raw, fmt)
    fields = await service.fields_for_type(tenant_db, asset_type_id)
    targets = [("name", "Name"), ("external_id", "External ID"), ("status", "Status")] + [
        (f"field_{f.id}", f.label) for f in fields
    ]
    suggestions = {}
    for target_key, target_label in targets:
        match = next((h for h in headers if h.strip().lower() == target_label.strip().lower()), None)
        if match:
            suggestions[target_key] = match

    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(
        request,
        "assets/import_preview.html",
        {
            **nav,
            "ctx": ctx,
            "token": token,
            "fmt": fmt,
            "asset_type_id": asset_type_id,
            "headers": headers,
            "targets": targets,
            "suggestions": suggestions,
        },
    )


@router.post("/import/commit", response_class=HTMLResponse)
async def import_commit(
    request: Request,
    token: str = Form(...),
    fmt: str = Form(...),
    asset_type_id: int = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    mapping = {key[len("map_") :]: value for key, value in form.items() if key.startswith("map_") and value}

    stash = import_stash_path(token)
    raw = stash.read_bytes()
    rows = importer.parse_rows(raw, fmt)
    result = await importer.commit_import(
        tenant_db, asset_type_id=asset_type_id, rows=rows, mapping=mapping, actor_id=ctx.user.id
    )
    stash.unlink(missing_ok=True)

    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "assets/import_result.html", {**nav, "ctx": ctx, "result": result})


# --------------------------------------------------------- cloud sync ----


@router.get("/sync", response_class=HTMLResponse)
async def sync_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    nav = await build_nav_context(ctx)
    connections = await sync_service.list_connections(tenant_db)
    return templates.TemplateResponse(request, "assets/sync.html", {**nav, "ctx": ctx, "connections": connections})


@router.post("/sync")
async def sync_create(
    request: Request,
    provider: str = Form(...),
    name: str = Form(...),
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    form = await request.form()
    config = {k[len("cfg_") :]: v for k, v in form.items() if k.startswith("cfg_")}
    await sync_service.create_connection(tenant_db, provider=provider, name=name.strip(), config=config)
    return RedirectResponse("/assets/sync", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sync/{connection_id}/test")
async def sync_test(
    connection_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    connection = await tenant_db.get(sync_service.SyncConnection, connection_id)
    message = "connection not found"
    if connection is not None:
        provider = sync_service.PROVIDERS.get(connection.provider)
        config = sync_service.decrypt_config(connection)
        ok, message = provider.test_connection(config) if provider else (False, "unknown provider")
    return RedirectResponse(f"/assets/sync?tested={connection_id}&message={message}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sync/{connection_id}/delete")
async def sync_delete(
    connection_id: int,
    tenant_db: AsyncSession = Depends(get_tenant_db),
    _: CurrentUser = Depends(require_login),
):
    connection = await tenant_db.get(sync_service.SyncConnection, connection_id)
    if connection is not None:
        await tenant_db.delete(connection)
        await tenant_db.commit()
    return RedirectResponse("/assets/sync", status_code=status.HTTP_303_SEE_OTHER)
