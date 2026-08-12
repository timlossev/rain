"""Platform-level administration: branding, tenants, users/roles, and a
read-only view of auth provider placeholders. internal_admin only, except
the tenant-switch action which any internal_admin uses to pick their
active tenant (client users are pinned to one and never see this)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from rain.core.config_store import config_store
from rain.core.rbac import require_internal_admin, require_login
from rain.core.security import hash_password
from rain.core.tenancy import CurrentUser, RequestContext, get_request_context
from rain.db.base import control_session
from rain.db.control_models import AuthProviderConfig, Session as SessionRow, Tenant, User
from rain.db.provisioning import InvalidSlugError, provision_tenant
from rain.web.nav import build_nav_context
from rain.web.templating import templates
from rain.web.uploads import UploadError, save_logo_upload

router = APIRouter(prefix="/admin")


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request, ctx: RequestContext = Depends(get_request_context), _: CurrentUser = Depends(require_login)
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "admin/dashboard.html", {**nav, "ctx": ctx})


@router.get("/branding", response_class=HTMLResponse)
async def branding_form(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    return templates.TemplateResponse(request, "admin/branding.html", {**nav, "ctx": ctx, "error": None})


@router.post("/branding")
async def branding_submit(
    request: Request,
    instance_name: str = Form(...),
    accent_color: str = Form(...),
    logo: UploadFile | None = None,
    ctx: RequestContext = Depends(get_request_context),
    user: CurrentUser = Depends(require_internal_admin),
):
    await config_store.set("instance_name", instance_name.strip(), updated_by=user.id)
    await config_store.set("accent_color", accent_color.strip(), updated_by=user.id)
    if logo is not None and logo.filename:
        try:
            logo_path = await save_logo_upload(logo)
            await config_store.set("logo_path", logo_path, updated_by=user.id)
        except UploadError as exc:
            nav = await build_nav_context(ctx)
            return templates.TemplateResponse(
                request, "admin/branding.html", {**nav, "ctx": ctx, "error": str(exc)}, status_code=400
            )
    return RedirectResponse("/admin/branding?ok=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/tenants", response_class=HTMLResponse)
async def tenants_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        result = await session.execute(select(Tenant).order_by(Tenant.name))
        tenants = list(result.scalars())
    return templates.TemplateResponse(
        request, "admin/tenants.html", {**nav, "ctx": ctx, "tenants": tenants, "error": None}
    )


@router.post("/tenants")
async def tenants_create(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    try:
        await provision_tenant(slug=slug.strip().lower(), name=name.strip())
    except InvalidSlugError as exc:
        nav = await build_nav_context(ctx)
        async with control_session() as session:
            result = await session.execute(select(Tenant).order_by(Tenant.name))
            tenants = list(result.scalars())
        return templates.TemplateResponse(
            request,
            "admin/tenants.html",
            {**nav, "ctx": ctx, "tenants": tenants, "error": str(exc)},
            status_code=400,
        )
    return RedirectResponse("/admin/tenants", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tenants/switch")
async def switch_tenant(request: Request, tenant_id: int = Form(...), _: CurrentUser = Depends(require_internal_admin)):
    session_row: SessionRow = request.state.session_row
    async with control_session() as session:
        row = await session.get(SessionRow, session_row.id)
        if row is not None:
            row.active_tenant_id = tenant_id
            await session.commit()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        users = list((await session.execute(select(User).order_by(User.email))).scalars())
        tenants = list((await session.execute(select(Tenant).order_by(Tenant.name))).scalars())
    return templates.TemplateResponse(
        request, "admin/users.html", {**nav, "ctx": ctx, "users": users, "tenants": tenants, "error": None}
    )


@router.post("/users")
async def users_create(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    role_key: str = Form(...),
    tenant_id: str = Form(""),
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    if role_key == "client" and not tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Client users must be assigned a tenant.")

    async with control_session() as session:
        session.add(
            User(
                email=email.strip().lower(),
                display_name=display_name.strip(),
                password_hash=hash_password(password),
                role_key=role_key,
                tenant_id=int(tenant_id) if tenant_id else None,
            )
        )
        await session.commit()
    return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(user_id: int, _: CurrentUser = Depends(require_internal_admin)):
    async with control_session() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.is_active = False
            await session.commit()
    return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth-providers", response_class=HTMLResponse)
async def auth_providers_list(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    _: CurrentUser = Depends(require_internal_admin),
):
    nav = await build_nav_context(ctx)
    async with control_session() as session:
        providers = list(
            (await session.execute(select(AuthProviderConfig).order_by(AuthProviderConfig.id))).scalars()
        )
    return templates.TemplateResponse(request, "admin/auth_providers.html", {**nav, "ctx": ctx, "providers": providers})
