from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import Sequence, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.core.user_names import resolve_user_emails
from rain.db.tenant_models import (
    ApprovalFlow,
    ApprovalFlowStep,
    Asset,
    ChangeApproval,
    ChangeApprovalDecision,
    ExportProfile,
    GroupMembership,
    SyslogEvent,
    Ticket,
    TicketAssetChange,
    TicketAssignmentChange,
    TicketComment,
    TicketFieldChange,
    TicketStatus,
    TicketStatusChange,
    TicketWatcher,
    WebhookConfig,
)
from rain.modules.tickets import notifications
from rain.modules.tickets.schemas import SEVERITIES, TICKET_TYPE_PREFIX

_SEQUENCE_NAMES = {"incident": "inc_number_seq", "vulnerability": "vuln_number_seq", "change": "chg_number_seq"}

# Tolerant of a missing or partial zero-pad ("INC-1" as well as
# "INC-000001") -- every number the app itself ever displays is already
# zero-padded to 6 digits, but someone typing one from memory (or a
# link/ticket_ref field) won't necessarily match that exactly.
_TICKET_REF_RE = re.compile(r"^(INC|VULN|CHG)-(\d+)$", re.IGNORECASE)


async def _next_ticket_number(db: AsyncSession, ticket_type: str) -> str:
    seq = Sequence(_SEQUENCE_NAMES[ticket_type])
    next_val = await db.scalar(select(seq.next_value()))
    return f"{TICKET_TYPE_PREFIX[ticket_type]}-{next_val:06d}"


async def create_ticket(
    db: AsyncSession,
    *,
    ticket_type: str,
    title: str,
    description: str | None,
    severity: str = "medium",
    asset_id: int | None = None,
    source_event_id: int | None = None,
    source_rule_id: int | None = None,
    source_correlation_rule_id: int | None = None,
    source_ticket_id: int | None = None,
    source_catalog_item_id: int | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    assignee_user_id: int | None = None,
    reporter_user_id: int | None = None,
    reported_anonymously: bool = False,
) -> Ticket:
    # reported_anonymously only means anything when there's no
    # reporter_user_id to begin with -- normalized here (not just left to
    # caller discipline) since "Reported by" on both the ticket detail
    # page and its PDF export check reporter_user_id first, so a caller
    # passing both would silently get attributed to reporter_user_id
    # everywhere despite also claiming reported_anonymously=True.
    reported_anonymously = reported_anonymously and reporter_user_id is None
    ticket = Ticket(
        ticket_number=await _next_ticket_number(db, ticket_type),
        ticket_type=ticket_type,
        title=title[:255],
        description=description,
        severity=severity,
        asset_id=asset_id,
        source_event_id=source_event_id,
        source_rule_id=source_rule_id,
        source_correlation_rule_id=source_correlation_rule_id,
        source_ticket_id=source_ticket_id,
        source_catalog_item_id=source_catalog_item_id,
        start_date=start_date,
        end_date=end_date,
        assignee_user_id=assignee_user_id,
        reporter_user_id=reporter_user_id,
        reported_anonymously=reported_anonymously,
    )
    db.add(ticket)
    await db.flush()

    if source_event_id is not None:
        event = await db.get(SyslogEvent, source_event_id)
        if event is not None:
            event.promoted_ticket_id = ticket.id

    await db.commit()

    # The reporter and (if set at creation time) the assignee are always
    # watchers -- not an opt-in the way the ticket detail page's "Watch"
    # button is for anyone else. No-op for an anonymous portal submission
    # (reporter_user_id is None) since there's no account to watch as.
    if reporter_user_id is not None:
        await add_watcher(db, ticket.id, reporter_user_id)
    if assignee_user_id is not None:
        await add_watcher(db, ticket.id, assignee_user_id)

    # Platform event rules (Admin > Platform Events) react to every newly
    # created ticket regardless of origin -- both this function's callers
    # (the manual "New ticket" form and the syslog auto-promotion path in
    # rain.modules.tickets.rules) land here, so hooking it in this single
    # choke point covers both. Imported locally to avoid a module-load-time
    # cycle (platform_events -> documents.service, notifications -> ... ->
    # back into this module).
    from rain.modules.tickets.platform_events import evaluate_ticket_created

    await evaluate_ticket_created(db, ticket)

    # No db.refresh(ticket) here: this session's connection carries a
    # schema_translate_map set once at checkout (see rain.db.base.
    # tenant_session), and a refresh *after* commit checks out a fresh
    # connection from the pool that doesn't have it -- the resulting
    # unqualified "FROM tickets" query landed in the wrong schema
    # entirely (asyncpg.exceptions.UndefinedTableError, confirmed via a
    # real request with DEBUG=true). Not needed anyway: the session was
    # created with expire_on_commit=False, so ticket's attributes
    # (including server-generated ones from the INSERT) are still
    # populated in memory after commit.
    return ticket


#: Column headers a list view is allowed to sort by, keyed by the query
#: string value the template's links use. Deliberately just real Ticket
#: columns -- Assignee/Asset would need a name-resolving join to sort
#: usefully (sorting by the raw id isn't), not built here.
SORTABLE_COLUMNS = {
    "ticket_number": Ticket.ticket_number,
    "title": Ticket.title,
    "severity": Ticket.severity,
    "status": Ticket.status,
    "created_at": Ticket.created_at,
}


def ticket_list_stmt(
    *,
    ticket_type: str | None = None,
    status: str | None = None,
    assigned_to: int | None = None,
    unassigned: bool = False,
    problematic_only: bool = False,
    sort: str | None = None,
    direction: str = "desc",
):
    """Shared statement builder -- used both by list_tickets() (full list,
    for exports/etc) and the Tickets screen's paginated query.
    `assigned_to` (a user id, for "My Incidents") and `unassigned` (for
    "Unassigned Incidents") are mutually exclusive; callers pick one.
    `sort` falls back to created_at (the pre-sorting default) for None or
    anything not in SORTABLE_COLUMNS, rather than erroring on a stale or
    hand-edited query string."""
    # selectinload(Ticket.approval): the list view's change rows show an
    # approved/unapproved indicator next to the title (list.html), which
    # needs ticket.approval.overall_status -- without eager-loading it
    # here, that's a lazy load in an async session (raises
    # MissingGreenlet) the first time a change row renders.
    stmt = select(Ticket).options(selectinload(Ticket.asset), selectinload(Ticket.approval))
    column = SORTABLE_COLUMNS.get(sort, Ticket.created_at)
    stmt = stmt.order_by(column.desc() if direction != "asc" else column.asc())
    if ticket_type:
        stmt = stmt.where(Ticket.ticket_type == ticket_type)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if unassigned:
        stmt = stmt.where(Ticket.assignee_user_id.is_(None))
    elif assigned_to is not None:
        stmt = stmt.where(Ticket.assignee_user_id == assigned_to)
    if problematic_only:
        stmt = stmt.where(Ticket.is_problematic.is_(True))
    return stmt


async def list_tickets(
    db: AsyncSession, *, ticket_type: str | None = None, status: str | None = None
) -> list[Ticket]:
    result = await db.execute(ticket_list_stmt(ticket_type=ticket_type, status=status))
    return list(result.scalars())


def _ticket_detail_stmt():
    return select(Ticket).options(
        selectinload(Ticket.asset),
        selectinload(Ticket.source_rule),
        selectinload(Ticket.source_correlation_rule),
        selectinload(Ticket.source_ticket),
        selectinload(Ticket.source_catalog_item),
        selectinload(Ticket.comments),
        selectinload(Ticket.status_changes),
        selectinload(Ticket.assignment_changes),
        selectinload(Ticket.asset_changes),
        selectinload(Ticket.field_changes),
        selectinload(Ticket.rule_triggers),
        selectinload(Ticket.approval).selectinload(ChangeApproval.decisions),
        selectinload(Ticket.approval).selectinload(ChangeApproval.flow).selectinload(ApprovalFlow.steps),
    )


async def get_ticket(db: AsyncSession, ticket_id: int) -> Ticket | None:
    result = await db.execute(_ticket_detail_stmt().where(Ticket.id == ticket_id))
    return result.scalar_one_or_none()


async def get_ticket_by_ref(db: AsyncSession, ref: str) -> Ticket | None:
    """`ref` is a ticket_number ("INC-000123"/"VULN-000045"/"CHG-000012",
    or the same with a short/unpadded number like "INC-123") -- the URL
    scheme ticket detail links use -- or, for back-compat with any link/
    bookmark built before that switch, a bare integer id."""
    ref = ref.strip()
    if ref.isdigit():
        ticket = await get_ticket(db, int(ref))
        if ticket is not None:
            return ticket
    match = _TICKET_REF_RE.match(ref)
    normalized = f"{match.group(1).upper()}-{int(match.group(2)):06d}" if match else ref
    result = await db.execute(_ticket_detail_stmt().where(Ticket.ticket_number == normalized))
    return result.scalar_one_or_none()


async def get_ticket_numbers(db: AsyncSession, ticket_ids: list[int]) -> dict[int, str]:
    """Bulk id -> ticket_number lookup -- e.g. for rendering a polymorphic
    document link ("ticket", linked_id) as INC-000123 instead of a bare
    database id, without eager-loading a full Ticket per row."""
    if not ticket_ids:
        return {}
    result = await db.execute(select(Ticket.id, Ticket.ticket_number).where(Ticket.id.in_(ticket_ids)))
    return {row.id: row.ticket_number for row in result}


async def is_watching(db: AsyncSession, ticket_id: int, user_id: int) -> bool:
    result = await db.execute(
        select(TicketWatcher).where(TicketWatcher.ticket_id == ticket_id, TicketWatcher.user_id == user_id)
    )
    return result.scalar_one_or_none() is not None


async def add_watcher(db: AsyncSession, ticket_id: int, user_id: int) -> None:
    if await is_watching(db, ticket_id, user_id):
        return
    db.add(TicketWatcher(ticket_id=ticket_id, user_id=user_id))
    await db.commit()


async def add_watcher_by_email(db: AsyncSession, ticket_id: int, email: str) -> None:
    """Same idea as add_watcher, for a watcher with no system account --
    backs Platform Response Rules' "Add a watcher" action. Case-
    insensitive de-dup (matches the DB-level partial unique index on
    (ticket_id, lower(email)), see TicketWatcher's docstring) so the
    same address configured on two different rules, or re-added by
    hand, doesn't produce a duplicate row/duplicate email."""
    email = email.strip()
    if not email:
        return
    result = await db.execute(
        select(TicketWatcher).where(
            TicketWatcher.ticket_id == ticket_id, func.lower(TicketWatcher.email) == email.lower()
        )
    )
    if result.scalar_one_or_none() is not None:
        return
    db.add(TicketWatcher(ticket_id=ticket_id, email=email))
    await db.commit()


async def remove_watcher(db: AsyncSession, ticket_id: int, user_id: int) -> None:
    result = await db.execute(
        select(TicketWatcher).where(TicketWatcher.ticket_id == ticket_id, TicketWatcher.user_id == user_id)
    )
    watcher = result.scalar_one_or_none()
    if watcher is not None:
        await db.delete(watcher)
        await db.commit()


async def _watcher_recipients(db: AsyncSession, ticket_id: int, *, exclude_user_id: int | None) -> set[str]:
    """Every watcher's email address -- resolved from control.users for a
    user_id row, taken as-is for an email row -- except exclude_user_id
    (the actor who triggered this, if any; only ever matches a user_id
    row, an email-only watcher was never "the actor" to begin with)."""
    result = await db.execute(select(TicketWatcher).where(TicketWatcher.ticket_id == ticket_id))
    watchers = list(result.scalars())
    user_ids = {w.user_id for w in watchers if w.user_id is not None}
    user_ids.discard(exclude_user_id)
    emails = {w.email for w in watchers if w.email}
    if user_ids:
        resolved = await resolve_user_emails(user_ids)
        emails |= {e for e in resolved.values() if e}
    return emails


async def _notify_watchers(
    db: AsyncSession, ticket: Ticket, *, exclude_user_id: int | None, subject: str, body: str
) -> None:
    """Emails every watcher of ticket except exclude_user_id (the actor who
    triggered this, if any) -- a silent no-op with no watchers, no
    resolvable email address, or no SMTP configured (send_email's own
    guard)."""
    recipients = list(await _watcher_recipients(db, ticket.id, exclude_user_id=exclude_user_id))
    if recipients:
        await notifications.send_email(recipients, subject, body)


async def _notify_approvers(db: AsyncSession, ticket: Ticket, step: ApprovalFlowStep) -> None:
    """Emails the step's approver(s) -- the individual approver_user_id, or
    every member of approver_group_id -- that a change ticket is waiting on
    their decision. Same silent-no-op guards as _notify_watchers."""
    user_ids: set[int] = set()
    if step.approver_user_id is not None:
        user_ids.add(step.approver_user_id)
    elif step.approver_group_id is not None:
        result = await db.execute(
            select(GroupMembership.user_id).where(GroupMembership.group_id == step.approver_group_id)
        )
        user_ids |= set(result.scalars())
    if not user_ids:
        return
    emails = await resolve_user_emails(user_ids)
    recipients = [e for e in emails.values() if e]
    if recipients:
        await notifications.send_email(
            recipients,
            f"[RAIN] Approval needed: {ticket.ticket_number}",
            f'{ticket.ticket_number}: {ticket.title}\n\nStep "{step.label}" is waiting on your approval.',
        )


async def add_comment(db: AsyncSession, ticket_id: int, author_user_id: int | None, body: str) -> TicketComment:
    comment = TicketComment(ticket_id=ticket_id, author_user_id=author_user_id, body=body)
    db.add(comment)
    await db.commit()
    ticket = await db.get(Ticket, ticket_id)
    if ticket is not None:
        await _notify_watchers(
            db,
            ticket,
            exclude_user_id=author_user_id,
            subject=f"[RAIN] New comment on {ticket.ticket_number}",
            body=f"{ticket.ticket_number}: {ticket.title}\n\n{body}",
        )
    return comment


async def list_statuses(db: AsyncSession, *, active_only: bool = False) -> list[TicketStatus]:
    stmt = select(TicketStatus).order_by(TicketStatus.sort_order, TicketStatus.label)
    if active_only:
        stmt = stmt.where(TicketStatus.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars())


async def get_status_by_key(db: AsyncSession, key: str) -> TicketStatus | None:
    result = await db.execute(select(TicketStatus).where(TicketStatus.key == key))
    return result.scalar_one_or_none()


async def update_status(
    db: AsyncSession, ticket: Ticket, new_status: str, *, changed_by_user_id: int | None = None
) -> bool:
    """Returns False (no-op) if new_status isn't one of this tenant's
    configured statuses -- the caller decides how to surface that. A no-op
    if new_status already equals the current status (no duplicate log
    entry for re-clicking the current pill)."""
    if new_status == ticket.status:
        return True
    status_row = await get_status_by_key(db, new_status)
    if status_row is None:
        return False
    old_status = ticket.status
    ticket.status = new_status
    ticket.closed_at = dt.datetime.now(dt.timezone.utc) if status_row.is_closed else None
    db.add(
        TicketStatusChange(
            ticket_id=ticket.id, changed_by_user_id=changed_by_user_id, from_status=old_status, to_status=new_status
        )
    )
    await db.commit()
    await _notify_watchers(
        db,
        ticket,
        exclude_user_id=changed_by_user_id,
        subject=f"[RAIN] {ticket.ticket_number} status changed",
        body=f"{ticket.ticket_number}: {ticket.title}\n\nStatus changed from {old_status} to {new_status}.",
    )
    return True


async def get_closed_status(db: AsyncSession) -> TicketStatus | None:
    """The status "Mark closed" (tickets list quick-action menu) applies --
    the tenant's first active, is_closed-flagged status by sort_order.
    None if the tenant hasn't configured one yet; the caller decides how
    to surface that (there's no sane single status to invent)."""
    result = await db.execute(
        select(TicketStatus)
        .where(TicketStatus.is_active.is_(True), TicketStatus.is_closed.is_(True))
        .order_by(TicketStatus.sort_order, TicketStatus.label)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_status_by_name(db: AsyncSession, name: str) -> TicketStatus | None:
    """Case-insensitive match on key or label -- backs "Mark cancelled"
    (tickets list quick-action menu, changes only), which has no dedicated
    boolean flag on TicketStatus the way is_closed does for "Mark closed".
    Matching by name instead of adding one more single-purpose column
    keeps this to a naming convention rather than more schema surface for
    a narrower need; a tenant just needs a status literally called
    "Cancelled" (or "cancelled") for the action to find it."""
    result = await db.execute(
        select(TicketStatus).where(
            TicketStatus.is_active.is_(True),
            (func.lower(TicketStatus.key) == name.lower()) | (func.lower(TicketStatus.label) == name.lower()),
        )
    )
    return result.scalars().first()


async def log_field_change(
    db: AsyncSession,
    ticket_id: int,
    field_name: str,
    from_value: str | None,
    to_value: str | None,
    *,
    changed_by_user_id: int | None = None,
    commit: bool = True,
) -> None:
    """Appends a generic field-change activity entry. Public (not just
    used by update_problematic/update_severity/update_title below, which
    take a from_value/to_value they've already computed) -- also called
    from outside this module (documents.router, platform_events'
    attach_document action) to log a document link/unlink against a
    ticket, since that's a system event, not a human comment, and the
    activity feed renders every field_name the same single-line way
    (Date - Actor - action; severity's values as pills, like a status
    change's) rather than a comment's two-line author/body layout. Takes
    a bare ticket_id rather than a loaded Ticket -- callers outside this
    module usually don't have one loaded already. commit=False lets a
    caller that's about to commit its own change anyway (e.g.
    update_severity) fold this into that same commit instead of a second
    round trip."""
    db.add(
        TicketFieldChange(
            ticket_id=ticket_id,
            changed_by_user_id=changed_by_user_id,
            field_name=field_name,
            from_value=from_value,
            to_value=to_value,
        )
    )
    if commit:
        await db.commit()


async def update_problematic(
    db: AsyncSession, ticket: Ticket, is_problematic: bool, *, changed_by_user_id: int | None = None
) -> None:
    if is_problematic == ticket.is_problematic:
        return
    old_value, new_value = str(ticket.is_problematic).lower(), str(is_problematic).lower()
    ticket.is_problematic = is_problematic
    await log_field_change(
        db, ticket.id, "is_problematic", old_value, new_value, changed_by_user_id=changed_by_user_id, commit=False
    )
    await db.commit()


async def _reset_approval_if_approved(db: AsyncSession, ticket: Ticket, *, changed_by_user_id: int | None) -> None:
    """Editing an approved change ticket -- title, priority, assignee, or
    affected asset -- invalidates the approvals already collected for it:
    what got approved isn't necessarily what's being shipped anymore.
    Resets the approval back to the first step (clearing every recorded
    decision, group and individual steps alike) so the flow has to run
    again in full, and logs that reset to the ticket's own activity feed
    -- not just a silent status flip -- so anyone reading the history
    sees why approval status changed with no new decision to explain it.
    A no-op for anything that isn't a change ticket currently sitting at
    "approved" (queried directly rather than via ticket.approval, which
    isn't guaranteed eager-loaded on every caller's Ticket instance)."""
    if ticket.ticket_type != "change":
        return
    result = await db.execute(
        select(ChangeApproval)
        .where(ChangeApproval.ticket_id == ticket.id)
        .options(selectinload(ChangeApproval.decisions))
    )
    approval = result.scalar_one_or_none()
    if approval is None or approval.overall_status != "approved":
        return
    for decision in list(approval.decisions):
        await db.delete(decision)
    approval.overall_status = "pending"
    approval.current_step_order = 0
    approval.completed_at = None
    await log_field_change(
        db,
        ticket.id,
        "approval_reset",
        None,
        "editing this change nullified its collected approvals -- it must be re-approved",
        changed_by_user_id=changed_by_user_id,
        commit=False,
    )


async def update_severity(
    db: AsyncSession, ticket: Ticket, new_severity: str, *, changed_by_user_id: int | None = None
) -> bool:
    """Returns False for an unrecognized severity, same shape as
    update_status's False for an unknown status."""
    if new_severity not in SEVERITIES:
        return False
    if new_severity == ticket.severity:
        return True
    old_severity = ticket.severity
    ticket.severity = new_severity
    await log_field_change(
        db, ticket.id, "severity", old_severity, new_severity, changed_by_user_id=changed_by_user_id, commit=False
    )
    await _reset_approval_if_approved(db, ticket, changed_by_user_id=changed_by_user_id)
    await db.commit()
    return True


async def update_title(
    db: AsyncSession, ticket: Ticket, new_title: str, *, changed_by_user_id: int | None = None
) -> bool:
    """Returns False (no-op) for a blank title -- the caller decides how
    to surface that, same shape as update_status's False for an unknown
    status."""
    new_title = new_title.strip()[:255]
    if not new_title or new_title == ticket.title:
        return True
    old_title = ticket.title
    ticket.title = new_title
    await log_field_change(
        db, ticket.id, "title", old_title, new_title, changed_by_user_id=changed_by_user_id, commit=False
    )
    await _reset_approval_if_approved(db, ticket, changed_by_user_id=changed_by_user_id)
    await db.commit()
    return True


async def update_assignee(
    db: AsyncSession, ticket: Ticket, new_assignee_user_id: int | None, *, changed_by_user_id: int | None = None
) -> None:
    """A no-op (no duplicate log entry) if new_assignee_user_id already
    equals the current assignee -- mirrors update_status's same guard."""
    if new_assignee_user_id == ticket.assignee_user_id:
        return
    old_assignee_user_id = ticket.assignee_user_id
    ticket.assignee_user_id = new_assignee_user_id
    db.add(
        TicketAssignmentChange(
            ticket_id=ticket.id,
            changed_by_user_id=changed_by_user_id,
            from_assignee_user_id=old_assignee_user_id,
            to_assignee_user_id=new_assignee_user_id,
        )
    )
    await _reset_approval_if_approved(db, ticket, changed_by_user_id=changed_by_user_id)
    await db.commit()
    # The ticket's owner is always a watcher -- not an opt-in the way the
    # ticket detail page's "Watch" button is for anyone else (same rule
    # create_ticket applies for the reporter/an assignee set at creation).
    if new_assignee_user_id is not None:
        await add_watcher(db, ticket.id, new_assignee_user_id)


async def update_asset(
    db: AsyncSession, ticket: Ticket, new_asset_id: int | None, *, changed_by_user_id: int | None = None
) -> None:
    """A no-op (no duplicate log entry) if new_asset_id already equals the
    current asset -- mirrors update_assignee's same guard."""
    if new_asset_id == ticket.asset_id:
        return
    old_asset_id = ticket.asset_id
    ticket.asset_id = new_asset_id
    db.add(
        TicketAssetChange(
            ticket_id=ticket.id,
            changed_by_user_id=changed_by_user_id,
            from_asset_id=old_asset_id,
            to_asset_id=new_asset_id,
        )
    )
    await _reset_approval_if_approved(db, ticket, changed_by_user_id=changed_by_user_id)
    await db.commit()


async def escalate_ticket(
    db: AsyncSession, ticket: Ticket, webhook: WebhookConfig, *, actor_user_id: int | None = None
) -> str:
    """Fires the tenant's one configured escalation webhook (Admin >
    Branding > Public incident portal -- reused there since it's already
    the "portal & ticket-adjacent tenant settings" page) for this single
    ticket, on demand. Unlike Platform Response Rules' own "Call a
    webhook" action, this isn't pattern-matched or automatic -- it's the
    "Escalate" button on the ticket detail page (and, for an
    authenticated portal visitor, next to their own tickets), fired by a
    human who decided this one needs attention now. Logs the outcome to
    the ticket's activity feed the same way a platform-rule firing does,
    and to the webhook's own alert_on_failure path on a failed call.
    Returns a short outcome string for the caller to flash back."""
    # Imported locally to avoid a module-load-time cycle: webhooks.service
    # imports tickets.correlation and tickets.rules, both of which import
    # this module -- same reason create_ticket's platform_events import
    # is local instead of top-level.
    from rain.modules.webhooks import service as webhook_service

    placeholders = {
        "ticket_number": ticket.ticket_number,
        "ticket_type": ticket.ticket_type,
        "title": ticket.title,
        "description": ticket.description or "",
        "severity": ticket.severity,
        "status": ticket.status,
    }
    result = await webhook_service.call_webhook(webhook, placeholders)
    if not result.success and webhook.alert_on_failure:
        await webhook_service.alert_webhook_failure(
            db, webhook, result, context=f"Escalation of {ticket.ticket_number}"
        )
    outcome = f"{webhook.name} -> {result.error}" if result.error else f"{webhook.name} -> HTTP {result.status_code}"
    await log_field_change(db, ticket.id, "escalated", None, outcome, changed_by_user_id=actor_user_id, commit=False)
    await db.commit()
    return outcome


async def list_approval_flows(db: AsyncSession) -> list[ApprovalFlow]:
    result = await db.execute(select(ApprovalFlow).options(selectinload(ApprovalFlow.steps)).order_by(ApprovalFlow.name))
    return list(result.scalars())


async def get_default_approval_flow(db: AsyncSession) -> ApprovalFlow | None:
    result = await db.execute(
        select(ApprovalFlow).options(selectinload(ApprovalFlow.steps)).where(ApprovalFlow.is_default.is_(True))
    )
    return result.scalar_one_or_none()


async def approval_flow_exists(db: AsyncSession, flow_id: int) -> bool:
    """Whether flow_id names a real, usable flow -- one with at least one
    step. Backs create_ticket's server-side requirement that a change
    ticket name a real flow at creation, rather than silently filing an
    unprotected one -- same "has steps" bar start_approval below already
    holds attaching a flow to."""
    flow = await db.get(ApprovalFlow, flow_id, options=[selectinload(ApprovalFlow.steps)])
    return flow is not None and bool(flow.steps)


async def start_approval(db: AsyncSession, ticket: Ticket, flow_id: int | None) -> None:
    """Attaches an approval instance to a change ticket. A no-op if
    flow_id is None or the flow has no steps -- ticket.approval stays
    unset, and the UI treats that as "no approval process configured"
    rather than a fake pre-approved state."""
    if flow_id is None:
        return
    flow = await db.get(ApprovalFlow, flow_id, options=[selectinload(ApprovalFlow.steps)])
    if flow is None or not flow.steps:
        return
    first_step = min(flow.steps, key=lambda s: s.sort_order)
    db.add(ChangeApproval(ticket_id=ticket.id, flow_id=flow.id, current_step_order=first_step.sort_order))
    await db.commit()
    await _notify_approvers(db, ticket, first_step)


async def is_eligible_approver(db: AsyncSession, step: ApprovalFlowStep, user_id: int) -> bool:
    if step.approver_user_id is not None:
        return step.approver_user_id == user_id
    if step.approver_group_id is not None:
        result = await db.execute(
            select(GroupMembership).where(
                GroupMembership.group_id == step.approver_group_id, GroupMembership.user_id == user_id
            )
        )
        return result.scalar_one_or_none() is not None
    return False


async def current_approval_step(db: AsyncSession, approval: ChangeApproval) -> ApprovalFlowStep | None:
    if approval.flow_id is None:
        return None
    result = await db.execute(
        select(ApprovalFlowStep).where(
            ApprovalFlowStep.flow_id == approval.flow_id, ApprovalFlowStep.sort_order == approval.current_step_order
        )
    )
    return result.scalar_one_or_none()


async def decide_approval_step(
    db: AsyncSession,
    approval: ChangeApproval,
    step: ApprovalFlowStep,
    *,
    decision: str,
    decided_by_user_id: int,
    comment: str | None = None,
) -> None:
    """Records the decision, then either short-circuits to "rejected" or
    advances to the next step (or to "approved", if that was the last
    one). approval.decisions/current_step_order/overall_status are all
    mutated on the same object the caller already holds, so a re-render
    right after this sees the update without a fresh query."""
    db.add(
        ChangeApprovalDecision(
            approval_id=approval.id,
            step_order=step.sort_order,
            step_label=step.label,
            decided_by_user_id=decided_by_user_id,
            decision=decision,
            comment=comment or None,
        )
    )
    next_step: ApprovalFlowStep | None = None
    if decision == "rejected":
        approval.overall_status = "rejected"
        approval.completed_at = dt.datetime.now(dt.timezone.utc)
    else:
        next_result = await db.execute(
            select(ApprovalFlowStep)
            .where(ApprovalFlowStep.flow_id == approval.flow_id, ApprovalFlowStep.sort_order > step.sort_order)
            .order_by(ApprovalFlowStep.sort_order)
            .limit(1)
        )
        next_step = next_result.scalar_one_or_none()
        if next_step is None:
            approval.overall_status = "approved"
            approval.completed_at = dt.datetime.now(dt.timezone.utc)
        else:
            approval.current_step_order = next_step.sort_order
    await db.commit()
    if next_step is not None:
        ticket = await db.get(Ticket, approval.ticket_id)
        if ticket is not None:
            await _notify_approvers(db, ticket, next_step)


async def list_tickets_pending_approval_for(db: AsyncSession, user_id: int) -> list[Ticket]:
    """Change tickets whose approval is pending and currently sitting on a
    step this user is eligible to decide -- named directly
    (approver_user_id) or reachable via group membership
    (approver_group_id) -- backing the client portal's "Pending my
    approval" tab. Same eligibility rule as is_eligible_approver, just
    evaluated as a set query instead of one step at a time."""
    member_group_ids = select(GroupMembership.group_id).where(GroupMembership.user_id == user_id)
    stmt = (
        select(Ticket)
        .join(ChangeApproval, ChangeApproval.ticket_id == Ticket.id)
        .join(
            ApprovalFlowStep,
            (ApprovalFlowStep.flow_id == ChangeApproval.flow_id)
            & (ApprovalFlowStep.sort_order == ChangeApproval.current_step_order),
        )
        .where(
            ChangeApproval.overall_status == "pending",
            (ApprovalFlowStep.approver_user_id == user_id) | (ApprovalFlowStep.approver_group_id.in_(member_group_ids)),
        )
        .order_by(Ticket.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars())


async def get_event(db: AsyncSession, event_id: int) -> SyslogEvent | None:
    return await db.get(SyslogEvent, event_id)


async def recent_events(db: AsyncSession, *, limit: int = 50) -> list[SyslogEvent]:
    result = await db.execute(select(SyslogEvent).order_by(SyslogEvent.id.desc()).limit(limit))
    return list(reversed(result.scalars().all()))


async def list_export_profiles(db: AsyncSession) -> list[ExportProfile]:
    """Ticket-scoped half of the shared export_profiles table -- see
    ExportProfile's docstring for why assets and tickets share one table
    (scope) instead of two."""
    result = await db.execute(
        select(ExportProfile).where(ExportProfile.scope == "ticket").order_by(ExportProfile.name)
    )
    return list(result.scalars())


async def save_export_profile(
    db: AsyncSession, *, name: str, fmt: str, columns: list[dict], actor_id: int
) -> ExportProfile:
    profile = ExportProfile(name=name, scope="ticket", asset_type_id=None, format=fmt, columns=columns, created_by=actor_id)
    db.add(profile)
    await db.commit()
    return profile


async def list_tickets_for_asset(db: AsyncSession, asset_id: int) -> list[Ticket]:
    """Every ticket (any type/status) with this asset currently set as
    its affected asset -- shown on the asset's own edit page and PDF
    export, under Linked Documents. Not the asset-change history
    (TicketAssetChange) -- just tickets currently pointed at it."""
    result = await db.execute(
        select(Ticket).where(Ticket.asset_id == asset_id).order_by(Ticket.created_at.desc())
    )
    return list(result.scalars())


async def list_tickets_reported_by(db: AsyncSession, user_id: int) -> list[dict]:
    """Backs the incident portal's "Tickets reported by me" table
    (rain.modules.portal). "Last update" is the more recent of the
    ticket's own updated_at (bumped by any status/severity/title/
    assignee/asset change -- see Ticket.updated_at's onupdate) and its
    newest comment, since a comment alone doesn't touch the ticket row
    itself; without folding that in, a ticket with only fresh comments
    and no field changes would read as stale. Deliberately not the full
    multi-source activity feed ticket detail builds (comments + every
    change table) -- this is a glance-level preview, not the record."""
    latest_comment = (
        select(TicketComment.ticket_id, func.max(TicketComment.created_at).label("latest_comment_at"))
        .group_by(TicketComment.ticket_id)
        .subquery()
    )
    last_update = func.greatest(Ticket.updated_at, latest_comment.c.latest_comment_at).label("last_update_at")
    stmt = (
        select(Ticket, last_update)
        .outerjoin(latest_comment, latest_comment.c.ticket_id == Ticket.id)
        .where(Ticket.reporter_user_id == user_id)
        .order_by(last_update.desc())
    )
    result = await db.execute(stmt)
    return [{"ticket": ticket, "last_update_at": last_update_at} for ticket, last_update_at in result.all()]


def build_activity(ticket: Ticket) -> list[dict]:
    """Comments, status changes, assignment changes, asset changes, field
    changes (severity/problematic/title), and (change tickets only) approval
    decisions interleaved into one chronological feed ("Activity"), each
    tagged with its kind so the caller (ticket detail screen, PDF export, or
    the client portal's own timeline modal) can render them differently.
    Shared so none of those three drift apart on what counts as "activity"
    or how it's ordered -- moved here from rain.modules.tickets.router (its
    original home) once the portal needed the exact same feed too."""
    approval_entries = (
        [{"kind": "approval_decision", "at": d.created_at, "item": d} for d in ticket.approval.decisions]
        if ticket.approval
        else []
    )
    return sorted(
        [{"kind": "comment", "at": c.created_at, "item": c} for c in ticket.comments]
        + [{"kind": "status_change", "at": sc.created_at, "item": sc} for sc in ticket.status_changes]
        + [{"kind": "assignment_change", "at": ac.created_at, "item": ac} for ac in ticket.assignment_changes]
        + [{"kind": "asset_change", "at": ac.created_at, "item": ac} for ac in ticket.asset_changes]
        + [{"kind": "field_change", "at": fc.created_at, "item": fc} for fc in ticket.field_changes]
        + approval_entries,
        key=lambda entry: entry["at"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
    )


def assignment_change_ids(ticket: Ticket) -> set[int | None]:
    """Every user id build_activity's assignment_change entries reference
    (who changed it, and the from/to assignee) -- feeds a batched
    rain.core.user_names.resolve_user_names call rather than one lookup
    per entry. Moved here alongside build_activity for the same reason:
    the client portal's timeline needs this too, not just the ticket
    detail screen."""
    ids: set[int | None] = set()
    for ac in ticket.assignment_changes:
        ids |= {ac.changed_by_user_id, ac.from_assignee_user_id, ac.to_assignee_user_id}
    return ids


def asset_change_ids(ticket: Ticket) -> set[int | None]:
    """Every asset id build_activity's asset_change entries reference (the
    from/to affected asset) -- feeds asset_names below."""
    ids: set[int | None] = set()
    for ac in ticket.asset_changes:
        ids |= {ac.from_asset_id, ac.to_asset_id}
    return ids


async def asset_names(db: AsyncSession, asset_ids: set[int | None]) -> dict[int, str]:
    """Batched name lookup for the asset picker's initial label and the
    activity feed's asset-change entries -- same shape as
    rain.core.user_names.resolve_user_names, but assets live in this same
    tenant db session (no cross-schema query needed, unlike users)."""
    ids = {i for i in asset_ids if i is not None}
    if not ids:
        return {}
    result = await db.execute(select(Asset).where(Asset.id.in_(ids)))
    return {a.id: a.name for a in result.scalars()}
