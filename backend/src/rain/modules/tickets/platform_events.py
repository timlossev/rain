"""Platform events: a second, independent rule layer on top of ticket
creation. Where TicketRule/rules.py decides *whether an incoming syslog
event becomes a ticket at all* (first match wins, evaluated by the
worker), this layer reacts *after* a ticket already exists -- of either
origin, auto-promoted or manually created -- and every active, matching
rule fires (not just the first), each running one or more actions:
notify Slack, notify email, call a webhook, attach a document, attach an
asset. Every firing is logged to platform_event_triggers and shown on the
ticket detail page, regardless of whether the individual actions
succeeded -- a failed Slack post shouldn't hide the fact the rule matched.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.core.crypto import decrypt_json
from rain.db.tenant_models import (
    Asset,
    Document,
    NotificationChannel,
    PlatformEventAction,
    PlatformEventRule,
    PlatformEventTrigger,
    Ticket,
    WebhookConfig,
)
from rain.modules.documents import service as document_service
from rain.modules.tickets import service as ticket_service
from rain.modules.tickets.notifications import send_email, send_slack
from rain.modules.webhooks import service as webhook_service

logger = logging.getLogger("rain.platform_events")

TRIGGER_EVENTS = [
    ("incident_created", "When an incident is created"),
    ("vulnerability_created", "When a vulnerability is created"),
    ("change_created", "When a change is created"),
]
MATCH_FIELDS = ["title", "description"]
ACTION_TYPES = [
    ("notify_slack", "Notify Slack"),
    ("notify_email", "Notify Email"),
    ("webhook", "Call a webhook"),
    ("attach_document", "Attach a document"),
    ("attach_asset", "Attach an asset"),
]

_TRIGGER_BY_TICKET_TYPE = {
    "incident": "incident_created",
    "vulnerability": "vulnerability_created",
    "change": "change_created",
}


async def evaluate_ticket_created(db: AsyncSession, ticket: Ticket) -> None:
    """Called once, right after a ticket is committed (both the manual
    creation route and the syslog auto-promotion path go through
    rain.modules.tickets.service.create_ticket, so hooking it there covers
    both origins). Never raises -- a broken rule/action must not take down
    ticket creation itself."""
    trigger_event = _TRIGGER_BY_TICKET_TYPE.get(ticket.ticket_type)
    if trigger_event is None:
        return

    try:
        stmt = (
            select(PlatformEventRule)
            .where(PlatformEventRule.is_active.is_(True), PlatformEventRule.trigger_event == trigger_event)
            .options(selectinload(PlatformEventRule.actions))
            .order_by(PlatformEventRule.sort_order)
        )
        rules = list((await db.execute(stmt)).scalars())
    except Exception:
        logger.exception("failed to load platform event rules for ticket %s", ticket.id)
        return

    for rule in rules:
        try:
            if _rule_matches(rule, ticket):
                await _fire_rule(db, rule, ticket)
        except Exception:
            logger.exception("platform event rule %s failed for ticket %s", rule.id, ticket.id)


def _rule_matches(rule: PlatformEventRule, ticket: Ticket) -> bool:
    value = getattr(ticket, rule.match_field, None)
    if not value:
        return False
    try:
        return re.search(rule.pattern, value) is not None
    except re.error:
        return False


async def _fire_rule(db: AsyncSession, rule: PlatformEventRule, ticket: Ticket) -> None:
    outcomes: list[str] = []
    for action in rule.actions:
        try:
            outcomes.append(await _run_action(db, action, ticket))
        except Exception as exc:
            logger.exception("platform event action %s (rule %s) failed for ticket %s", action.id, rule.id, ticket.id)
            outcomes.append(f"{_action_label(action.action_type)}: failed ({exc})")

    summary = "; ".join(outcomes) if outcomes else "matched (no actions configured)"
    db.add(PlatformEventTrigger(rule_id=rule.id, rule_name=rule.name, ticket_id=ticket.id, summary=summary))
    # Also onto the ticket's own unified activity feed, not just the rule's
    # trigger-history table -- a rule firing is a system-caused change to
    # this specific ticket and belongs alongside status/severity/etc
    # changes, not only visible by navigating to the rule.
    await ticket_service.log_field_change(db, ticket.id, "platform_rule", rule.name, summary, commit=False)
    await db.commit()


def _action_label(action_type: str) -> str:
    return dict(ACTION_TYPES).get(action_type, action_type)


async def _run_action(db: AsyncSession, action: PlatformEventAction, ticket: Ticket) -> str:
    config = action.config or {}
    label = _action_label(action.action_type)

    if action.action_type in ("notify_slack", "notify_email"):
        channel_id = config.get("channel_id")
        channel = await db.get(NotificationChannel, channel_id) if channel_id else None
        if channel is None:
            return f"{label}: channel no longer exists"
        channel_config = decrypt_json(channel.config_encrypted)
        if action.action_type == "notify_slack":
            webhook_url = channel_config.get("webhook_url")
            if not webhook_url:
                return f"{label}: channel has no webhook URL"
            await send_slack(webhook_url, f"*{ticket.ticket_number}* ({ticket.severity}) {ticket.title}")
            return f"{label}: sent to '{channel.name}'"
        recipients = channel_config.get("recipients", [])
        if not recipients:
            return f"{label}: channel has no recipients"
        subject = f"[RAIN] {ticket.ticket_number}: {ticket.title}"
        body = f"{ticket.ticket_number} ({ticket.severity}) created.\n\n{ticket.description or ''}"
        await send_email(recipients, subject, body)
        return f"{label}: sent to '{channel.name}'"

    if action.action_type == "webhook":
        webhook_id = config.get("webhook_id")
        webhook = await db.get(WebhookConfig, webhook_id) if webhook_id else None
        if webhook is None:
            return f"{label}: webhook no longer exists"
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
                db, webhook, result, context=f"Platform Response Rule action on {ticket.ticket_number}"
            )
        if result.error:
            return f"{label}: {webhook.name} -> {result.error}"
        return f"{label}: {webhook.name} -> HTTP {result.status_code}"

    if action.action_type == "attach_document":
        document_id = config.get("document_id")
        document = await db.get(Document, document_id) if document_id else None
        if document is None:
            return f"{label}: document no longer exists"
        await document_service.add_link(db, document.id, "ticket", ticket.id, created_by=None)
        # Also on the Activity feed, not just this rule-trigger log --
        # a link is a change to the ticket regardless of what caused it.
        await ticket_service.log_field_change(
            db, ticket.id, "document", None, f"{document.doc_number}: {document.title}"
        )
        return f"{label}: linked {document.doc_number}"

    if action.action_type == "attach_asset":
        asset_id = config.get("asset_id")
        asset = await db.get(Asset, asset_id) if asset_id else None
        if asset is None:
            return f"{label}: asset no longer exists"
        if ticket.asset_id is None:
            ticket.asset_id = asset.id
            await db.commit()
            return f"{label}: linked {asset.name}"
        return f"{label}: ticket already has an asset -- left unchanged"

    return f"{label}: unknown action type"
