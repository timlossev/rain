"""Root-cause assistance for a ticket, especially incidents: two honest,
non-causal signals composed into one comment, plus the plumbing to trigger
that either on demand or automatically at closure.

Deliberately not "AI root cause analysis" -- nothing in this app (or
river, its only ML dependency) does causal reasoning. What it *can* do,
cheaply, from data already on hand:

- summarize_chronic: if this ticket accumulated repeat occurrences (see
  rain.modules.tickets.rules' "repetition" promotion_type) or was fed by
  more than one promoted syslog event, pull those events back via
  SyslogEvent.promoted_ticket_id and summarize what was common across
  them (host/program distribution, first/last seen) -- the kind of thing
  a human would do by hand scrolling the timeline, just faster.
- find_similar_closed_tickets: full-text search (rain.modules.search's
  own websearch_to_tsquery/ts_rank pattern) for past *closed* tickets
  whose title/description reads similarly, on the theory that "we saw
  this before" is often the fastest real lead toward a cause, even
  though the search itself has no notion of causality.

Both are surfaced as one comment (analyze()), authored by RAIN System
(author_user_id=None, same convention rules.combine_event_into_ticket
already uses) -- see rain.modules.tickets.router's on-demand /analyze
route and service.update_status's opt-in auto-trigger."""
from __future__ import annotations

import datetime as dt
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import SyslogEvent, Ticket, TicketStatus

# rain.core.tenant_config key: opt-in, default off (see that module's
# DEFAULTS) -- an automatic comment on every closed ticket is noise for a
# tenant that never wanted it, so this only fires once an admin turns it
# on under Tickets > Platform Response Rules (a reaction to a ticket
# event, same as every rule on that screen, not a status property).
AUTO_ROOT_CAUSE_CONFIG_KEY = "auto_root_cause_on_close"

# Cap how many promoted events summarize_chronic pulls back -- a genuinely
# chronic rule/group can accumulate a lot of occurrences, and this only
# needs enough of them to characterize the pattern, not the full history.
_MAX_CHRONIC_EVENTS = 500


async def summarize_chronic(db: AsyncSession, ticket: Ticket) -> str | None:
    """None if this ticket was never fed more than one promoted syslog
    event -- a plain single-event incident has no "pattern" to summarize
    beyond the event itself, already in its description."""
    result = await db.execute(
        select(SyslogEvent)
        .where(SyslogEvent.promoted_ticket_id == ticket.id)
        .order_by(SyslogEvent.received_at)
        .limit(_MAX_CHRONIC_EVENTS)
    )
    events = list(result.scalars())
    if len(events) < 2:
        return None

    hosts = Counter(e.host for e in events if e.host)
    programs = Counter(e.program for e in events if e.program)
    first, last = events[0], events[-1]
    span = last.received_at - first.received_at if first.received_at and last.received_at else None

    lines = [f"{len(events)} promoted syslog events tied to this ticket"]
    if span is not None:
        lines[0] += f" over {_format_span(span)}"
    lines[0] += "."
    if hosts:
        top_host, top_host_n = hosts.most_common(1)[0]
        lines.append(f"Most common host: {top_host} ({top_host_n}/{len(events)}).")
    if programs:
        top_program, top_program_n = programs.most_common(1)[0]
        lines.append(f"Most common program: {top_program} ({top_program_n}/{len(events)}).")
    return " ".join(lines)


def _format_span(span: dt.timedelta) -> str:
    total_minutes = max(1, int(span.total_seconds() // 60))
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours, minutes = divmod(total_minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h" if hours else f"{days}d"


async def find_similar_closed_tickets(db: AsyncSession, ticket: Ticket, *, limit: int = 5) -> list[dict]:
    """Past closed tickets whose title/description full-text-matches this
    one's title -- same websearch_to_tsquery/ts_rank pattern rain.modules.
    search.service.search uses, just scoped to is_closed statuses and
    excluding this ticket itself. [] if the title has nothing searchable
    left after websearch_to_tsquery parses it (very short/all-stopword
    titles), not an error."""
    tsquery = func.websearch_to_tsquery("english", ticket.title)
    rank = func.ts_rank(Ticket.search_vector, tsquery)
    closed_keys = select(TicketStatus.key).where(TicketStatus.is_closed.is_(True))
    stmt = (
        select(Ticket, rank.label("rank"))
        .where(
            Ticket.id != ticket.id,
            Ticket.status.in_(closed_keys),
            Ticket.search_vector.op("@@")(tsquery),
        )
        .order_by(rank.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [{"ticket": t, "rank": rank} for t, rank in rows]


async def analyze(db: AsyncSession, ticket: Ticket) -> str | None:
    """Composes both signals into one comment body. None (nothing to add)
    if neither turned anything up -- callers should skip posting a comment
    at all rather than adding a content-free one."""
    chronic = await summarize_chronic(db, ticket)
    similar = await find_similar_closed_tickets(db, ticket)

    if chronic is None and not similar:
        return None

    lines = [
        "Root cause assistance (automated) - statistical/historical signals, not a determined cause:",
    ]
    if chronic is not None:
        lines.append("")
        lines.append("Repetition pattern:")
        lines.append(f"  {chronic}")
    if similar:
        lines.append("")
        lines.append("Similar past incidents (closed, ranked by text match):")
        for row in similar:
            t = row["ticket"]
            closed = t.closed_at.strftime("%Y-%m-%d") if t.closed_at else "-"
            lines.append(f"  {t.ticket_number} ({closed}): {t.title}")
    return "\n".join(lines)
