"""Regex rule matching and auto-promotion. Evaluated by the worker
(rain.modules.tickets.listener) against every persisted syslog event, and
reused by the rule editor's "test against a sample" action."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import Asset, SyslogEvent, Ticket, TicketRule
from rain.modules.tickets import service


async def find_matching_rule(db: AsyncSession, event: SyslogEvent) -> TicketRule | None:
    result = await db.execute(select(TicketRule).where(TicketRule.is_active.is_(True)).order_by(TicketRule.sort_order))
    for rule in result.scalars():
        if rule_matches(rule, event):
            return rule
    return None


def field_matches(match_field: str, pattern: str, event: SyslogEvent) -> bool:
    """The one matcher every regex-based rule concept in this app shares
    (TicketRule here, CorrelationRule's base filter in
    rain.modules.tickets.correlation) -- so "does this event match this
    field/pattern" always means exactly the same thing everywhere."""
    value = getattr(event, match_field, None)
    if not value:
        return False
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


def rule_matches(rule: TicketRule, event: SyslogEvent) -> bool:
    return field_matches(rule.match_field, rule.pattern, event)


async def apply_rule(db: AsyncSession, rule: TicketRule, event: SyslogEvent) -> Ticket:
    asset_id = None
    if rule.asset_match_field:
        value = getattr(event, rule.asset_match_field, None)
        if value:
            result = await db.execute(select(Asset).where(Asset.external_id == value))
            asset = result.scalar_one_or_none()
            asset_id = asset.id if asset else None

    title = rule.title_template.format(message=event.message or "", host=event.host or "", program=event.program or "")

    return await service.create_ticket(
        db,
        ticket_type=rule.ticket_type,
        title=title,
        # The full event, not just message -- see build_event_description's
        # own docstring (same reasoning applies to a policy-triggered
        # promotion as a manual one).
        description=service.build_event_description(event),
        severity=rule.severity,
        asset_id=asset_id,
        source_event_id=event.id,
        source_rule_id=rule.id,
    )
