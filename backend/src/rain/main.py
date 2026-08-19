"""FastAPI application factory.

Startup order matters: migrations must run before anything touches the
DB, config must be cached before the first request, and nav modules must
be imported (for their registration side effects) before any template
tries to render the tree.
"""
from __future__ import annotations

import html
import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from rain.core.config_store import config_store
from rain.core.rbac import require_internal_admin
from rain.core.tenancy import AuthRequiredError, CurrentUser, TenantRequiredError, get_current_user_optional
from rain.db import migrate, provisioning
from rain.db.base import dispose_engine
from rain.settings import get_settings
from rain.web.templating import templates
from rain.worker_runtime import WorkerServices

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rain")

SETUP_EXEMPT_PREFIXES = ("/setup", "/media", "/static", "/healthz")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # uvicorn's default lifespan="auto" mode swallows the traceback of a
    # startup exception (only logs "Application startup failed. Exiting."),
    # which makes failures here needlessly hard to diagnose -- log it
    # ourselves before letting it propagate.
    worker_services: WorkerServices | None = None
    try:
        logger.info("waiting for database...")
        await migrate.wait_for_database()
        logger.info("running control-schema migrations...")
        await migrate.upgrade_control_async()
        logger.info("reconciling tenant schemas...")
        await provisioning.reconcile_all_tenant_schemas()
        logger.info("loading global config...")
        await config_store.load_all()
        await config_store.start_listener()
        # EMBED_WORKER=true folds the syslog listener + rule engine +
        # notifications + calendar sweep + LDAP sync into this same
        # process instead of a separate `worker` container/service --
        # see docker-compose.yml's "minimal mode" comment and
        # rain.worker_runtime's own docstring for why this doesn't just
        # call the same code path the standalone `rain-worker` process
        # does (that one blocks on its own until killed; this process is
        # already kept alive by uvicorn's event loop).
        if get_settings().embed_worker:
            logger.info("EMBED_WORKER=true -- starting worker services in this process...")
            worker_services = WorkerServices()
            await worker_services.start()
        logger.info("RAIN startup complete")
    except Exception:
        logger.exception("RAIN startup failed")
        raise
    try:
        yield
    finally:
        if worker_services is not None:
            await worker_services.stop()
        await config_store.stop_listener()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    # docs_url/redoc_url/openapi_url=None turns off FastAPI's own public
    # defaults for these three -- the app's own gated routes below replace
    # them, behind require_internal_admin like every other platform-wide
    # setting (rain.core.rbac), rather than leaving the API surface (schema,
    # every route/param) world-readable to an unauthenticated caller.
    app = FastAPI(
        title="RAIN",
        description=(
            "Response to Asynchronous Interactions in Networks -- a self-hosted, "
            "multi-tenant IT system of record (asset registry, syslog-driven "
            "ticketing, document repository). This spec covers every server-"
            "rendered route the web UI itself calls; RAIN has no separate JSON/"
            "REST API for external integration today -- see /admin/webhooks and "
            "Platform Response Rules for the supported way to react to events "
            "from outside the app."
        ),
        lifespan=lifespan,
        debug=settings.debug,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    uploads_dir = Path(settings.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Only the branding subfolder is served statically (logos need to
    # render on the public login/setup page, before auth). Everything else
    # under uploads_dir -- tenant documents, the CSV/JSON import stash --
    # must go through an authenticated, tenant-scoped route instead; mounting
    # the whole uploads_dir here would make it all fetchable by URL alone.
    branding_dir = uploads_dir / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media/branding", StaticFiles(directory=str(branding_dir)), name="media_branding")

    static_dir = Path(__file__).resolve().parent / "web" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Import module nav registrations for their side effects (adding nodes
    # to rain.core.nav_registry) before any router that renders the tree.
    from rain.modules.admin import nav as _admin_nav  # noqa: F401
    from rain.modules.assets import nav as _assets_nav  # noqa: F401
    from rain.modules.calendar import nav as _calendar_nav  # noqa: F401
    from rain.modules.documents import nav as _documents_nav  # noqa: F401
    from rain.modules.tickets import nav as _tickets_nav  # noqa: F401

    from rain.modules.admin.router import router as admin_router
    from rain.modules.assets.router import router as assets_router
    from rain.modules.auth.router import router as auth_router
    from rain.modules.calendar.router import router as calendar_router
    from rain.modules.catalog.router import router as catalog_router
    from rain.modules.documents.router import router as documents_router
    from rain.modules.portal.router import router as portal_router
    from rain.modules.search.router import router as search_router
    from rain.modules.setup.router import router as setup_router
    from rain.modules.tickets.live import router as tickets_live_router
    from rain.modules.tickets.router import router as tickets_router

    app.include_router(setup_router)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(assets_router)
    app.include_router(tickets_router)
    app.include_router(tickets_live_router)
    app.include_router(catalog_router)
    app.include_router(documents_router)
    app.include_router(calendar_router)
    app.include_router(search_router)
    app.include_router(portal_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

    # Gated replacements for FastAPI's own /docs, /redoc, /openapi.json
    # (disabled above) -- internal_admin only, same bar as every other
    # platform-wide setting (rain.core.rbac.require_internal_admin).
    @app.get("/openapi.json", include_in_schema=False)
    async def openapi_spec(_: CurrentUser = Depends(require_internal_admin)):
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui(_: CurrentUser = Depends(require_internal_admin)):
        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - API docs")

    @app.get("/redoc", include_in_schema=False)
    async def redoc_ui(_: CurrentUser = Depends(require_internal_admin)):
        return get_redoc_html(openapi_url="/openapi.json", title=f"{app.title} - API docs")

    @app.get("/", include_in_schema=False)
    async def index(user: CurrentUser | None = Depends(get_current_user_optional)):
        if user is None:
            return RedirectResponse("/login")
        return RedirectResponse("/tickets")

    @app.middleware("http")
    async def enforce_setup_wizard(request: Request, call_next):
        path = request.url.path
        if not any(path.startswith(p) for p in SETUP_EXEMPT_PREFIXES):
            from rain.modules.setup.router import setup_already_done

            if not await setup_already_done():
                return RedirectResponse("/setup", status_code=303)
        return await call_next(request)

    @app.exception_handler(AuthRequiredError)
    async def auth_required_handler(request: Request, exc: AuthRequiredError):
        # Preserve the query string too (not just the path) -- e.g. a link
        # that carries ?tenant=<slug> as a post-login hint (see
        # rain.modules.auth.router.login_submit) would otherwise lose it here.
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)

    @app.exception_handler(TenantRequiredError)
    async def tenant_required_handler(request: Request, exc: TenantRequiredError):
        user = getattr(request.state, "current_user", None)
        if user is not None and getattr(user, "is_internal_admin", False):
            return RedirectResponse("/admin/tenants", status_code=303)
        return templates.TemplateResponse(request, "errors/no_tenant.html", {}, status_code=409)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code in (403, 404) and "text/html" in request.headers.get("accept", ""):
            template = "errors/403.html" if exc.status_code == 403 else "errors/404.html"
            return templates.TemplateResponse(request, template, {}, status_code=exc.status_code)
        return HTMLResponse(f"<h1>{exc.status_code}</h1><p>{exc.detail}</p>", status_code=exc.status_code)

    # Catch-all so an unhandled exception is never silently a bare 500 --
    # this is what surfaced the log_config=None fix in run_web() (see
    # rain.cli): without it, a route handler's unhandled exception showed
    # nothing anywhere, in any logger, for reasons that traced back to
    # uvicorn's own logging setup interfering with this app's loggers.
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("unhandled exception in %s %s", request.method, request.url.path)
        if settings.debug:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            body = f"<h1>500 Internal Server Error</h1><pre>{html.escape(tb)}</pre>"
            return HTMLResponse(body, status_code=500)
        return HTMLResponse("Internal Server Error", status_code=500)

    return app


app = create_app()
