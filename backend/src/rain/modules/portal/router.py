"""The public incident portal: a single page at /portal/<tenant slug> for
filing an incident without going through the full app -- no sidebar/
topbar. An anonymous visitor gets a deliberately bare-bones form ("New
ticket" and, once signed in, "Tickets reported by me"), plus "Today's
events" (rain.modules.calendar), shown to everyone regardless of
sign-in status. A signed-in visitor additionally gets a search bar and
two more tabs, Approvals and Documents. Reachable with or without a
session (rain.core.tenancy.get_current_user_optional, not
get_current_user), gated per-tenant by TenantConfig flags an admin sets
on Admin > Branding:

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

import io
import re
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select

from rain.core.tenancy import CurrentUser, get_current_user_optional
from rain.core.tenant_config import get_tenant_config, get_tenant_configs
from rain.core.user_names import resolve_user_names
from rain.db.base import control_session, tenant_session
from rain.db.control_models import Tenant
from rain.modules.calendar import service as calendar_service
from rain.modules.catalog import service as catalog_service
from rain.modules.documents import service as document_service
from rain.modules.documents import storage as document_storage
from rain.modules.tickets import service as ticket_service
from rain.modules.tickets.schemas import SEVERITIES, TICKET_TYPE_PREFIX
from rain.web.templating import templates

router = APIRouter(prefix="/portal", tags=["Portal"])

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


async def _resolve_portal_tenant_and_flags(
    request: Request, tenant_slug: str, user: CurrentUser | None
) -> tuple[Tenant, dict[str, Any]] | HTMLResponse:
    """Tenant resolution + the wrong-tenant check only -- no require-auth
    gate. Shared by _resolve_portal_access below (which adds that gate
    for every route that always needs it: submitting a ticket, opening a
    catalog form, the ticket timeline) and by portal_form (which applies
    its own looser gate: an anonymous visitor is let onto the page, in a
    restricted "Shareable documents only" mode, when portal_require_auth
    is on but this tenant has at least one document marked shareable --
    see that route)."""
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

    return tenant, flags


async def _resolve_portal_access(
    request: Request, tenant_slug: str, user: CurrentUser | None
) -> tuple[Tenant, dict[str, Any]] | HTMLResponse | RedirectResponse:
    """Single choke point for tenant resolution and the wrong-tenant/
    require-auth gate, shared by every route below except portal_form
    (see _resolve_portal_tenant_and_flags) so those can't silently drift
    on what's allowed through -- which is exactly how an earlier version
    of this module let a signed-in wrong-tenant visitor reach GET
    (disclosing the target tenant's name) while POST correctly blocked
    the same visitor.

    Returns either (tenant, portal_flags) for the caller to proceed
    with -- `user` was confirmed to belong to `tenant` (or be None and
    anonymous access is allowed) -- or a Response the caller should
    return immediately as-is."""
    resolved = await _resolve_portal_tenant_and_flags(request, tenant_slug, user)
    if not isinstance(resolved, tuple):
        return resolved
    tenant, flags = resolved

    if flags["portal_require_auth"] and user is None:
        return RedirectResponse(f"/login?next=/portal/{tenant_slug}", status_code=status.HTTP_303_SEE_OTHER)

    return tenant, flags


@router.get("/{tenant_slug}", response_class=HTMLResponse)
async def portal_form(
    request: Request,
    tenant_slug: str,
    created: str = "",
    error: str = "",
    ticket_status: str | None = None,
    page: int | None = None,
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    resolved = await _resolve_portal_tenant_and_flags(request, tenant_slug, user)
    if not isinstance(resolved, tuple):
        return resolved
    tenant, flags = resolved

    async with tenant_session(tenant.schema_name) as tenant_db:
        shareable_documents = await document_service.list_shareable_documents(tenant_db)
        shareable_documents_label = await get_tenant_config(
            tenant_db, "portal_shareable_documents_label", "Shareable documents"
        )

        # portal_require_auth normally bounces an anonymous visitor to
        # /login before this page renders at all (see _resolve_portal_
        # access, used by every other route below) -- but a document
        # marked shareable is meant to be reachable by literally anyone,
        # "Trust Center"-style, even on a tenant that otherwise locks the
        # rest of the portal down. So: still redirect if there's nothing
        # shareable to show (nothing here for an anonymous visitor to see
        # anyway); otherwise let them through in a restricted mode that
        # only ever renders the Shareable documents tab -- everything
        # else on this page stays exactly as gated as it already was.
        anonymous_shared_only = flags["portal_require_auth"] and user is None
        if anonymous_shared_only and not shareable_documents:
            return RedirectResponse(f"/login?next=/portal/{tenant_slug}", status_code=status.HTTP_303_SEE_OTHER)

        # Same "no filter in the URL at all" -> "active" default as the
        # main app's ticket list (rain.modules.tickets.router.
        # list_tickets) -- ticket_status="" (the "All statuses" dropdown
        # option, which always submits the param) explicitly opts back
        # into everything.
        effective_status = "active" if ticket_status is None else ticket_status
        # This whole page has no server-tracked "which tab is open" state
        # (app.js's [data-tabs] is purely client-side, reset on every full
        # page load) -- a GET reload triggered by the status filter would
        # otherwise silently bounce the visitor back to the first tab
        # (Request Something), losing their place on Report Something
        # right after they used the very control that's on that tab.
        # ticket_status being present in the URL at all (even "", from
        # "All statuses") is the signal this reload was that filter, not
        # a fresh page visit -- same reasoning extends to `created`,
        # whose redirect (below) also never carried a tab hint before
        # now: a visitor who just filed a report from this tab landing
        # back on Request Something instead, with no sign their
        # submission actually went through in the table right below
        # where they were, was the same class of bug. `page` (from
        # clicking Prev/Next on this same table) is the same signal for
        # the same reason.
        active_tab = (
            "shared"
            if anonymous_shared_only
            else "tickets" if ticket_status is not None or created or page is not None else "catalog"
        )

        reported = (
            await ticket_service.list_tickets_reported_by(tenant_db, user.id, status=effective_status, page=page or 1)
            if user is not None
            else []
        )
        statuses = await ticket_service.list_statuses(tenant_db) if user is not None else []
        # Confirmed against this tenant's own tickets, not just pattern-
        # matched -- the regex alone still lets a well-formed-but-fake
        # number ("INC-999999") through, which isn't content injection
        # any more (the format is fixed) but is still a free, pointless
        # spoof of "your ticket was just filed" worth closing off given
        # this is one indexed lookup, only run when `created` is present.
        created_ticket = (
            await ticket_service.get_ticket_by_ref(tenant_db, created) if _TICKET_NUMBER_RE.match(created) else None
        )
        # Pending Actions and Document Archive stay signed-in-only --
        # report.html gates both tabs behind {% if user %}, so there's no
        # reason to run either query for an anonymous visitor. Request
        # Something (catalog_items) is normally open to every visitor
        # regardless of sign-in status too (gated only by this tenant's
        # own portal_require_auth, same as tickets always were -- see
        # portal_catalog_form/submit below) -- except in
        # anonymous_shared_only mode, where nothing but Shareable
        # documents is meant to be reachable, so it's skipped there the
        # same as the signed-in-only tabs.
        pending_approval = await ticket_service.list_tickets_pending_approval_for(tenant_db, user.id) if user is not None else []
        documents = await document_service.list_documents(tenant_db) if user is not None else []
        catalog_items = (
            [] if anonymous_shared_only else await catalog_service.list_catalog_items(tenant_db, active_only=True)
        )
        # Shown to every visitor, signed in or not -- operational notices
        # (a maintenance window, a renewal due today) are tenant-wide
        # information, not tied to one person's account. Still suppressed
        # in anonymous_shared_only mode for the same reason as
        # catalog_items above: that mode renders nothing but the
        # Shareable documents tab.
        todays_events = [] if anonymous_shared_only else await calendar_service.list_entries_due_today(tenant_db)
        # Same webhook the ticket detail page's own Escalate button uses
        # (Admin > Branding); only meaningful once signed in, since the
        # "Tickets reported by me" table it appears next to only renders
        # for one.
        escalation_webhook_id = await get_tenant_config(tenant_db, "escalation_webhook_id", None) if user is not None else None

    return templates.TemplateResponse(
        request,
        "portal/report.html",
        {
            "tenant": tenant,
            "user": user,
            "branded": flags["portal_branded"],
            "anonymous_shared_only": anonymous_shared_only,
            "interactions": PORTAL_INTERACTIONS,
            "severities": SEVERITIES,
            "reported": reported,
            "statuses": statuses,
            "selected_status": ticket_status,
            "active_tab": active_tab,
            "pending_approval": pending_approval,
            "documents": documents,
            "shareable_documents": shareable_documents,
            "shareable_documents_label": shareable_documents_label,
            "catalog_items": catalog_items,
            "todays_events": todays_events,
            "can_escalate": escalation_webhook_id is not None,
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


@router.get("/{tenant_slug}/catalog/{item_key}", response_class=HTMLResponse)
async def portal_catalog_form(
    request: Request,
    tenant_slug: str,
    item_key: str,
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    access = await _resolve_portal_access(request, tenant_slug, user)
    if not isinstance(access, tuple):
        return access
    tenant, flags = access
    # Not signed-in-only -- gated by this tenant's own portal_require_auth
    # (already enforced by _resolve_portal_access above), the same as the
    # plain incident form. A catalog submission with no session attributes
    # the same way an anonymous ticket already does (reported_anonymously,
    # see portal_catalog_submit below).

    async with tenant_session(tenant.schema_name) as tenant_db:
        item = await catalog_service.get_catalog_item_by_key(tenant_db, item_key)
        if item is None or not item.is_active:
            return RedirectResponse(f"/portal/{tenant_slug}", status_code=status.HTTP_303_SEE_OTHER)
        rendered = await catalog_service.render_fields(tenant_db, item)

    return templates.TemplateResponse(
        request,
        "portal/catalog_form.html",
        {
            "tenant": tenant,
            "user": user,
            "branded": flags["portal_branded"],
            "item": item,
            "rendered_fields": rendered,
            "submitted": {},
            "errors": [],
        },
    )


@router.post("/{tenant_slug}/catalog/{item_key}")
async def portal_catalog_submit(
    request: Request,
    tenant_slug: str,
    item_key: str,
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    access = await _resolve_portal_access(request, tenant_slug, user)
    if not isinstance(access, tuple):
        return access
    tenant, flags = access

    async with tenant_session(tenant.schema_name) as tenant_db:
        item = await catalog_service.get_catalog_item_by_key(tenant_db, item_key)
        if item is None or not item.is_active:
            return RedirectResponse(f"/portal/{tenant_slug}", status_code=status.HTTP_303_SEE_OTHER)

        form = await request.form()
        # Same attribution rule as portal_create_ticket just above: a
        # signed-in visitor's answer to reporter_user_id, an anonymous
        # one's to reported_anonymously (submit_catalog_item passes that
        # straight through to ticket_service.create_ticket).
        result = await catalog_service.submit_catalog_item(
            tenant_db, item, form, reporter_user_id=user.id if user is not None else None, reported_anonymously=user is None
        )
        if result.errors:
            rendered = await catalog_service.render_fields(tenant_db, item)
            submitted = {f.field_key: form.get(f"answer_{f.field_key}", "") for f in item.fields}
            return templates.TemplateResponse(
                request,
                "portal/catalog_form.html",
                {
                    "tenant": tenant,
                    "user": user,
                    "branded": flags["portal_branded"],
                    "item": item,
                    "rendered_fields": rendered,
                    "submitted": submitted,
                    "errors": result.errors,
                },
            )

    return RedirectResponse(
        f"/portal/{tenant_slug}?created={result.ticket.ticket_number}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/{tenant_slug}/tickets/{ticket_ref}", response_class=HTMLResponse)
async def portal_ticket_timeline(
    request: Request,
    tenant_slug: str,
    ticket_ref: str,
    user: CurrentUser | None = Depends(get_current_user_optional),
):
    """The client portal's own lightweight ticket view: a read-only
    activity timeline rendered into a modal (app.js's [data-ticket-
    timeline] handler fetches this and injects it), not the full ticket
    detail/edit page -- "only the updates," per the ask this exists for,
    with a full "Edit ticket" link out to /tickets/<ref> (require_login,
    same as ever) for anyone who wants the real thing. This route itself
    changes nothing.

    Signed-in-only, and only for a ticket this visitor reported
    themselves -- same reporter_user_id == user.id scope as the "Tickets
    reported by me" table this is opened from, tighter than what a
    client/client_admin could actually reach via the full app (any
    ticket in their tenant), since the portal's whole ethos is a
    deliberately narrow, self-service surface. A 404 either way (never
    403) for "not signed in," "no such ticket," and "not your ticket" --
    an anonymous or wrong-visitor request shouldn't learn which one it
    was."""
    access = await _resolve_portal_access(request, tenant_slug, user)
    if not isinstance(access, tuple):
        return access
    tenant, _flags = access
    if user is None:
        return templates.TemplateResponse(request, "errors/404.html", {}, status_code=404)

    async with tenant_session(tenant.schema_name) as tenant_db:
        ticket = await ticket_service.get_ticket_by_ref(tenant_db, ticket_ref)
        if ticket is None or ticket.reporter_user_id != user.id:
            return templates.TemplateResponse(request, "errors/404.html", {}, status_code=404)

        status_labels = {s.key: s.label for s in await ticket_service.list_statuses(tenant_db)}
        activity = ticket_service.build_activity(ticket)
        user_names = await resolve_user_names(
            {ticket.reporter_user_id, ticket.assignee_user_id}
            | {c.author_user_id for c in ticket.comments}
            | {sc.changed_by_user_id for sc in ticket.status_changes}
            | ticket_service.assignment_change_ids(ticket)
            | {ac.changed_by_user_id for ac in ticket.asset_changes}
            | {fc.changed_by_user_id for fc in ticket.field_changes}
            | ({d.decided_by_user_id for d in ticket.approval.decisions} if ticket.approval else set())
        )
        asset_names = await ticket_service.asset_names(
            tenant_db, {ticket.asset_id} | ticket_service.asset_change_ids(ticket)
        )

    return templates.TemplateResponse(
        request,
        "portal/_ticket_timeline.html",
        {
            "tenant": tenant,
            "ticket": ticket,
            "activity": activity,
            "user_names": user_names,
            "asset_names": asset_names,
            "status_labels": status_labels,
        },
    )


@router.get("/{tenant_slug}/shared-documents/{doc_ref}/download")
async def portal_shared_document_download(tenant_slug: str, doc_ref: str):
    """The Shareable documents tab's own download link -- deliberately not
    rain.modules.documents.router.download_document (require_login, and
    resolves its tenant from the session via get_tenant_db, neither of
    which fits a visitor with no account at all). Public by design, same
    as the tab itself: no _resolve_portal_access call, no user parameter,
    404 for a document that either doesn't exist in this tenant or exists
    but isn't marked is_shareable -- a signed-out visitor guessing a
    document's id must not be able to fetch anything past what the tab
    already shows."""
    tenant = await _resolve_portal_tenant(tenant_slug)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    async with tenant_session(tenant.schema_name) as tenant_db:
        doc = await document_service.get_document_by_ref(tenant_db, doc_ref)
        if doc is None or not doc.is_shareable:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        data = document_storage.get_storage().read(doc.storage_key)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=doc.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )
