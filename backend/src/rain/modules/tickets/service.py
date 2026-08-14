from __future__ import annotations

import datetime as dt

from sqlalchemy import Sequence, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import (
    ApprovalFlow,
    ApprovalFlowStep,
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
)
from rain.modules.tickets.schemas import SEVERITIES, TICKET_TYPE_PREFIX

_SEQUENCE_NAMES = {"incident": "inc_number_seq", "vulnerability": "vuln_number_seq", "change": "chg_number_seq"}


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
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    assignee_user_id: int | None = None,
    reporter_user_id: int | None = None,
) -> Ticket:
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
        start_date=start_date,
        end_date=end_date,
        assignee_user_id=assignee_user_id,
        reporter_user_id=reporter_user_id,
    )
    db.add(ticket)
    await db.flush()

    if source_event_id is not None:
        event = await db.get(SyslogEvent, source_event_id)
        if event is not None:
            event.promoted_ticket_id = ticket.id

    await db.commit()

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
    chronic_only: bool = False,
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
    if chronic_only:
        stmt = stmt.where(Ticket.is_chronic.is_(True))
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
    """`ref` is a ticket_number ("INC-000123"/"VULN-000045"/"CHG-000012")
    -- the URL scheme ticket detail links use -- or, for back-compat with
    any link/bookmark built before that switch, a bare integer id."""
    if ref.isdigit():
        ticket = await get_ticket(db, int(ref))
        if ticket is not None:
            return ticket
    result = await db.execute(_ticket_detail_stmt().where(Ticket.ticket_number == ref))
    return result.scalar_one_or_none()


async def get_ticket_numbers(db: AsyncSession, ticket_ids: list[int]) -> dict[int, str]:
    """Bulk id -> ticket_number lookup -- e.g. for rendering a polymorphic
    document link ("ticket", linked_id) as INC-000123 instead of a bare
    database id, without eager-loading a full Ticket per row."""
    if not ticket_ids:
        return {}
    result = await db.execute(select(Ticket.id, Ticket.ticket_number).where(Ticket.id.in_(ticket_ids)))
    return {row.id: row.ticket_number for row in result}


async def add_comment(db: AsyncSession, ticket_id: int, author_user_id: int | None, body: str) -> TicketComment:
    comment = TicketComment(ticket_id=ticket_id, author_user_id=author_user_id, body=body)
    db.add(comment)
    await db.commit()
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
    used by update_chronic/update_severity/update_title below, which
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


async def update_chronic(
    db: AsyncSession, ticket: Ticket, is_chronic: bool, *, changed_by_user_id: int | None = None
) -> None:
    if is_chronic == ticket.is_chronic:
        return
    old_value, new_value = str(ticket.is_chronic).lower(), str(is_chronic).lower()
    ticket.is_chronic = is_chronic
    await log_field_change(
        db, ticket.id, "is_chronic", old_value, new_value, changed_by_user_id=changed_by_user_id, commit=False
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
