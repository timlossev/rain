"""The public incident portal: a single, deliberately bare-bones page at
/portal/<tenant slug> for filing an incident without going through the
full app -- "New ticket" and "Tickets reported by me," nothing else, no
sidebar/topbar. Reachable with or without a session (rain.core.tenancy.
get_current_user_optional, not get_current_user), gated per-tenant by
two TenantConfig flags an admin sets on Admin > Branding:

  - portal_require_auth: if true, a visitor with no session is bounced
    to /login?next=... instead of being able to submit anonymously.
  - portal_branded: if true, the page shows this instance's branding
    (logo/instance name/accent color) the same as every authenticated
    page; if false, it shows only the tenant's own name on a neutral,
    unaccented page.

Tenant resolution here is purely from the URL slug (no session needed at
all), unlike every other tenant-scoped route in the app, which resolves
the active tenant from the session (rain.core.tenancy.get_active_tenant).
That's the whole reason this is its own module instead of a route on
rain.modules.tickets.router: it can't use get_request_context/
get_tenant_db, which both assume a session already picked a tenant.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from rain.core.tenancy import CurrentUser, get_current_user_optional
from rain.core.tenant_config import get_tenant_config
from rain.db.base import control_session, tenant_session
from rain.db.control_models import Tenant
from rain.modules.tickets import service as ticket_service
from rain.modules.tickets.schemas import SEVERITIES
from rain.web.templating import templates

router = APIRouter(prefix="/portal")

# A registry, not a single hardcoded ticket_type, so a future bare-bones
# service catalog (docs/architecture.md's roadmap) can add more request
# types here -- "request access," "new equipment," whatever a tenant
# wants requestable through this same page -- each one just needs an
# entry here and, if it needs to end up somewhere other than a plain
# incident, a branch in _ticket_type_for. Everything else on this page
# (auth gating, tenant resolution, branding, the reported-by-me table)
# is already generic across whatever's in this list, not incident-
# specific. Today there's exactly one, because that's all that was asked
# for -- this is the wiring, not the catalog itself.
PORTAL_INTERACTIONS: list[tuple[str, str]] = [
    ("incident", "Report an incident"),
]


def _ticket_type_for(interaction: str) -> str | None:
    """None if `interaction` isn't one of PORTAL_INTERACTIONS -- callers
    must treat that as a validation error, not silently fall back to a
    default, so a crafted form field can never file into a ticket type
    this portal doesn't actually offer."""
    return {"incident": "incident"}.get(interaction)


async def _resolve_portal_tenant(tenant_slug: str) -> Tenant | None:
    async with control_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active.is_(True))
        )
        return result.scalar_one_or_none()


def _is_wrong_tenant(user: CurrentUser | None, tenant: Tenant) -> bool:
    """True for a signed-in user who isn't this tenant's -- an
    internal_admin spans every tenant, but a client/client_admin is
    pinned to exactly one (home_tenant_id), and someone signed in for a
    *different* one shouldn't have their ticket silently attributed to
    (or be silently let into) an organization they don't belong to."""
    if user is None or user.is_internal_admin:
        return False
    return user.home_tenant_id != tenant.id


@router.get("/{tenant_slug}", response_class=HTMLResponse)
async def portal_form(
    request: Request,
    tenant_slug: str,
    created: str = "",
    error: str = "",
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    tenant = await _resolve_portal_tenant(tenant_slug)
    if tenant is None:
        return templates.TemplateResponse(request, "errors/404.html", {}, status_code=404)

    wrong_tenant = _is_wrong_tenant(user, tenant)
    effective_user = None if wrong_tenant else user

    async with tenant_session(tenant.schema_name) as tenant_db:
        require_auth = await get_tenant_config(tenant_db, "portal_require_auth", True)
        # Only redirect to login when that would actually help -- a
        # signed-in-but-wrong-tenant visitor is already authenticated,
        # so bouncing them to /login would just bounce them straight
        # back out (login_form redirects an already-signed-in user away
        # from the login page entirely); showing the plain "wrong
        # tenant" message instead, below, is the only response that
        # actually explains anything.
        if require_auth and effective_user is None and not wrong_tenant:
            return RedirectResponse(f"/login?next=/portal/{tenant_slug}", status_code=status.HTTP_303_SEE_OTHER)

        reported = (
            await ticket_service.list_tickets_reported_by(tenant_db, effective_user.id)
            if effective_user is not None
            else []
        )
        branded = await get_tenant_config(tenant_db, "portal_branded", True)

    return templates.TemplateResponse(
        request,
        "portal/report.html",
        {
            "tenant": tenant,
            "user": effective_user,
            "wrong_tenant": wrong_tenant,
            "branded": branded,
            "interactions": PORTAL_INTERACTIONS,
            "severities": SEVERITIES,
            "reported": reported,
            "created": created,
            "error": error,
        },
    )


@router.post("/{tenant_slug}/tickets")
async def portal_create_ticket(
    tenant_slug: str,
    interaction: str = Form("incident"),
    title: str = Form(...),
    description: str = Form(""),
    severity: str = Form("medium"),
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    tenant = await _resolve_portal_tenant(tenant_slug)
    if tenant is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    ticket_type = _ticket_type_for(interaction)
    if ticket_type is None:
        return RedirectResponse(f"/portal/{tenant_slug}?error=Unknown+request+type.", status_code=status.HTTP_303_SEE_OTHER)
    if not title.strip():
        return RedirectResponse(f"/portal/{tenant_slug}?error=Title+is+required.", status_code=status.HTTP_303_SEE_OTHER)
    if severity not in SEVERITIES:
        severity = "medium"

    wrong_tenant = _is_wrong_tenant(user, tenant)
    effective_user = None if wrong_tenant else user

    async with tenant_session(tenant.schema_name) as tenant_db:
        require_auth = await get_tenant_config(tenant_db, "portal_require_auth", True)
        if wrong_tenant or (require_auth and effective_user is None):
            # Same reasoning as the GET route above: redirect back to
            # the page itself rather than duplicate its login-vs-message
            # branching here -- it'll show whichever is correct.
            return RedirectResponse(f"/portal/{tenant_slug}", status_code=status.HTTP_303_SEE_OTHER)

        ticket = await ticket_service.create_ticket(
            tenant_db,
            ticket_type=ticket_type,
            title=title.strip(),
            description=description.strip() or None,
            severity=severity,
            reporter_user_id=effective_user.id if effective_user is not None else None,
            reported_anonymously=effective_user is None,
        )

    return RedirectResponse(
        f"/portal/{tenant_slug}?created={ticket.ticket_number}", status_code=status.HTTP_303_SEE_OTHER
    )
