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

A signed-in visitor whose own tenant isn't the one in the URL is always
turned away with a plain 403 (see _resolve_portal_access), regardless of
portal_require_auth -- that flag controls whether *an* account is
required, not whether an account for a *different* tenant is accepted.

Tenant resolution here is purely from the URL slug (no session needed at
all), unlike every other tenant-scoped route in the app, which resolves
the active tenant from the session (rain.core.tenancy.get_active_tenant).
That's the whole reason this is its own module instead of a route on
rain.modules.tickets.router: it can't use get_request_context/
get_tenant_db, which both assume a session already picked a tenant.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from rain.core.tenancy import CurrentUser, get_current_user_optional
from rain.core.tenant_config import get_tenant_configs
from rain.db.base import control_session, tenant_session
from rain.db.control_models import Tenant
from rain.modules.documents import service as document_service
from rain.modules.tickets import service as ticket_service
from rain.modules.tickets.schemas import SEVERITIES, TICKET_TYPE_PREFIX
from rain.web.templating import templates

router = APIRouter(prefix="/portal")

# A registry, not a single hardcoded ticket_type, so a future bare-bones
# service catalog (docs/architecture.md's roadmap) can add more request
# types here -- "request access," "new equipment," whatever a tenant
# wants requestable through this same page -- each one just needs an
# entry here; _ticket_type_for derives from this same list, so adding
# one is sufficient on its own, nothing else to keep in sync. Everything
# else on this page (auth gating, tenant resolution, branding, the
# reported-by-me table) is already generic across whatever's in this
# list, not incident-specific. Today there's exactly one, because that's
# all that was asked for -- this is the wiring, not the catalog itself.
PORTAL_INTERACTIONS: list[tuple[str, str]] = [
    ("incident", "Report an incident"),
]

# Server-side text for every error this page's own POST handler can
# redirect back with. `error` arrives as a query param on a page that's
# meant to be publicly linkable and (with portal_branded on) carries the
# instance's own branding -- looking the code up here rather than
# rendering whatever string shows up on the wire means a crafted link
# can never inject arbitrary text into that trusted-looking banner.
_PORTAL_ERRORS: dict[str, str] = {
    "unknown_interaction": "Unknown request type.",
    "title_required": "Title is required.",
}

# What a genuine "Submitted as ..." confirmation looks like -- the
# `created` query param is validated against this before display for the
# same reason as _PORTAL_ERRORS above, rather than trusting whatever
# value is on the wire.
_TICKET_NUMBER_RE = re.compile(r"^(?:" + "|".join(TICKET_TYPE_PREFIX.values()) + r")-\d{6}$")


def _ticket_type_for(interaction: str) -> str | None:
    """None if `interaction` isn't a key in PORTAL_INTERACTIONS -- callers
    must treat that as a validation error, not silently fall back to a
    default, so a crafted form field can never file into a ticket type
    this portal doesn't actually offer. Every entry today maps 1:1 onto
    an existing Ticket.ticket_type (its own key IS the type), which is
    why this doesn't need a separate mapping the way a future interaction
    that *isn't* just a plain ticket might."""
    valid_keys = {key for key, _label in PORTAL_INTERACTIONS}
    return interaction if interaction in valid_keys else None


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


async def _resolve_portal_access(
    request: Request, tenant_slug: str, user: CurrentUser | None
) -> tuple[Tenant, dict[str, Any]] | HTMLResponse | RedirectResponse:
    """Single choke point for tenant resolution and the wrong-tenant/
    require-auth gate, shared by both routes below so the two can't
    silently drift on what's allowed to through -- which is exactly how
    an earlier version of this module let a signed-in wrong-tenant
    visitor reach GET (disclosing the target tenant's name) while POST
    correctly blocked the same visitor.

    Returns either (tenant, portal_flags) for the caller to proceed
    with -- `user` was confirmed to belong to `tenant` (or be None and
    anonymous access is allowed) -- or a Response the caller should
    return immediately as-is."""
    tenant = await _resolve_portal_tenant(tenant_slug)
    if tenant is None:
        return templates.TemplateResponse(request, "errors/404.html", {}, status_code=404)

    if _is_wrong_tenant(user, tenant):
        # Answered without ever opening this tenant's schema or
        # rendering anything tenant-specific (errors/403.html is
        # generic), so a signed-in visitor of another tenant learns
        # nothing beyond "this slug resolves to some tenant" -- already
        # observable from the 404-vs-not-404 split, which is inherent to
        # any slug-routed public page and not specific to this check.
        return templates.TemplateResponse(request, "errors/403.html", {}, status_code=403)

    async with tenant_session(tenant.schema_name) as tenant_db:
        flags = await get_tenant_configs(tenant_db, ["portal_require_auth", "portal_branded"])

    if flags["portal_require_auth"] and user is None:
        return RedirectResponse(f"/login?next=/portal/{tenant_slug}", status_code=status.HTTP_303_SEE_OTHER)

    return tenant, flags


@router.get("/{tenant_slug}", response_class=HTMLResponse)
async def portal_form(
    request: Request,
    tenant_slug: str,
    created: str = "",
    error: str = "",
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    access = await _resolve_portal_access(request, tenant_slug, user)
    if not isinstance(access, tuple):
        return access
    tenant, flags = access

    async with tenant_session(tenant.schema_name) as tenant_db:
        reported = await ticket_service.list_tickets_reported_by(tenant_db, user.id) if user is not None else []
        # Confirmed against this tenant's own tickets, not just pattern-
        # matched -- the regex alone still lets a well-formed-but-fake
        # number ("INC-999999") through, which isn't content injection
        # any more (the format is fixed) but is still a free, pointless
        # spoof of "your ticket was just filed" worth closing off given
        # this is one indexed lookup, only run when `created` is present.
        created_ticket = (
            await ticket_service.get_ticket_by_ref(tenant_db, created) if _TICKET_NUMBER_RE.match(created) else None
        )
        # Only meaningful for a signed-in visitor -- an anonymous one never
        # sees the tabbed layout these back (report.html gates both behind
        # {% if user %}), so there's no reason to run either query for one.
        pending_approval = await ticket_service.list_tickets_pending_approval_for(tenant_db, user.id) if user is not None else []
        documents = await document_service.list_documents(tenant_db) if user is not None else []

    return templates.TemplateResponse(
        request,
        "portal/report.html",
        {
            "tenant": tenant,
            "user": user,
            "branded": flags["portal_branded"],
            "interactions": PORTAL_INTERACTIONS,
            "severities": SEVERITIES,
            "reported": reported,
            "pending_approval": pending_approval,
            "documents": documents,
            "created": created_ticket.ticket_number if created_ticket is not None else "",
            "error": _PORTAL_ERRORS.get(error, ""),
        },
    )


@router.post("/{tenant_slug}/tickets")
async def portal_create_ticket(
    request: Request,
    tenant_slug: str,
    interaction: str = Form("incident"),
    title: str = Form(...),
    description: str = Form(""),
    severity: str = Form("medium"),
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    access = await _resolve_portal_access(request, tenant_slug, user)
    if not isinstance(access, tuple):
        return access
    tenant, _flags = access

    ticket_type = _ticket_type_for(interaction)
    if ticket_type is None:
        return RedirectResponse(f"/portal/{tenant_slug}?error=unknown_interaction", status_code=status.HTTP_303_SEE_OTHER)
    if not title.strip():
        return RedirectResponse(f"/portal/{tenant_slug}?error=title_required", status_code=status.HTTP_303_SEE_OTHER)
    if severity not in SEVERITIES:
        severity = "medium"

    async with tenant_session(tenant.schema_name) as tenant_db:
        ticket = await ticket_service.create_ticket(
            tenant_db,
            ticket_type=ticket_type,
            title=title.strip(),
            description=description.strip() or None,
            severity=severity,
            reporter_user_id=user.id if user is not None else None,
            reported_anonymously=user is None,
        )

    return RedirectResponse(
        f"/portal/{tenant_slug}?created={ticket.ticket_number}", status_code=status.HTTP_303_SEE_OTHER
    )
