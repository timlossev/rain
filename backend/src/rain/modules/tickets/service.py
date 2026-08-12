from __future__ import annotations

import datetime as dt

from sqlalchemy import Sequence, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.db.tenant_models import SyslogEvent, Ticket, TicketComment
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


async def list_tickets(
    db: AsyncSession, *, ticket_type: str | None = None, status: str | None = None
) -> list[Ticket]:
    stmt = select(Ticket).options(selectinload(Ticket.asset)).order_by(Ticket.created_at.desc())
    if ticket_type:
        stmt = stmt.where(Ticket.ticket_type == ticket_type)
    if status:
        stmt = stmt.where(Ticket.status == status)
    result = await db.execute(stmt)
    return list(result.scalars())


async def get_ticket(db: AsyncSession, ticket_id: int) -> Ticket | None:
    stmt = (
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(selectinload(Ticket.asset), selectinload(Ticket.comments))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def add_comment(db: AsyncSession, ticket_id: int, author_user_id: int | None, body: str) -> TicketComment:
    comment = TicketComment(ticket_id=ticket_id, author_user_id=author_user_id, body=body)
    db.add(comment)
    await db.commit()
    return comment


async def update_status(db: AsyncSession, ticket: Ticket, new_status: str) -> None:
    ticket.status = new_status
    ticket.closed_at = dt.datetime.now(dt.timezone.utc) if new_status == "closed" else None
    await db.commit()


async def get_event(db: AsyncSession, event_id: int) -> SyslogEvent | None:
    return await db.get(SyslogEvent, event_id)


async def recent_events(db: AsyncSession, *, limit: int = 50) -> list[SyslogEvent]:
    result = await db.execute(select(SyslogEvent).order_by(SyslogEvent.id.desc()).limit(limit))
    return list(reversed(result.scalars().all()))
