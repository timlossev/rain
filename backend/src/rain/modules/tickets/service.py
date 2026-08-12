from __future__ import annotations

import datetime as dt

from sqlalchemy import Sequence, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import SyslogEvent, Ticket, TicketComment, TicketStatus, TicketStatusChange
from rain.modules.tickets.schemas import TICKET_TYPE_PREFIX

_SEQUENCE_NAMES = {"incident": "inc_number_seq", "vulnerability": "vuln_number_seq"}


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


def ticket_list_stmt(*, ticket_type: str | None = None, status: str | None = None):
    """Shared statement builder -- used both by list_tickets() (full list,
    for exports/etc) and the Tickets screen's paginated query."""
    stmt = select(Ticket).options(selectinload(Ticket.asset)).order_by(Ticket.created_at.desc())
    if ticket_type:
        stmt = stmt.where(Ticket.ticket_type == ticket_type)
    if status:
        stmt = stmt.where(Ticket.status == status)
    return stmt


async def list_tickets(
    db: AsyncSession, *, ticket_type: str | None = None, status: str | None = None
) -> list[Ticket]:
    result = await db.execute(ticket_list_stmt(ticket_type=ticket_type, status=status))
    return list(result.scalars())


async def get_ticket(db: AsyncSession, ticket_id: int) -> Ticket | None:
    stmt = (
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(
            selectinload(Ticket.asset),
            selectinload(Ticket.comments),
            selectinload(Ticket.status_changes),
            selectinload(Ticket.rule_triggers),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


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


async def get_event(db: AsyncSession, event_id: int) -> SyslogEvent | None:
    return await db.get(SyslogEvent, event_id)


async def recent_events(db: AsyncSession, *, limit: int = 50) -> list[SyslogEvent]:
    result = await db.execute(select(SyslogEvent).order_by(SyslogEvent.id.desc()).limit(limit))
    return list(reversed(result.scalars().all()))
