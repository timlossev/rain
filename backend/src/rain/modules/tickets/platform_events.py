"""Platform events: a second, independent rule layer on top of ticket
creation. Where TicketRule/rules.py decides *whether an incoming syslog
event becomes a ticket at all* (first match wins, evaluated by the
worker), this layer reacts *after* a ticket already exists -- of either
origin, auto-promoted or manually created -- to one of several
lifecycle triggers (see TRIGGER_EVENTS: created, closed, or, change
tickets only, fully approved), and every active, matching rule fires
(not just the first), each running one or more actions: notify Slack,
notify email, call a webhook, invoke a Chat Completions API webhook and
post its reply as a comment, attach a document, attach an asset, mark
the ticket problematic, analyze root cause (optionally AI-narrated, see
below), or add a watcher (a system user or a bare email). Every firing
is logged to platform_event_triggers and shown on the ticket detail
page, regardless of whether the individual actions succeeded -- a
failed Slack post shouldn't hide the fact the rule matched.

analyze_root_cause (rain.modules.tickets.rootcause.analyze) used to be
a single tenant-wide "auto-analyze on every closed ticket" checkbox
(rootcause.AUTO_ROOT_CAUSE_CONFIG_KEY, since removed) rather than an
action here. As a checkbox it couldn't be scoped -- a tenant that only
wanted this for, say, incidents matching "database" had no way to say
so short of turning it on for every closed ticket tenant-wide. As an
action it gets the same match_field/pattern targeting every other
action already has for free, on whichever "<type> is closed"
trigger(s) a rule author actually wants it for.

analyze_root_cause's config is optionally {"webhook_id": <a kind=
"chat_completions" WebhookConfig>} -- rootcause.analyze's two signals
(repeat-occurrence pattern, similar closed tickets) are deliberately
not causal reasoning on their own (see that module's own docstring for
why), but they're exactly the evidence a human would start from when
actually reasoning about a cause. With no webhook picked, this action
posts rootcause.analyze's plain comment unchanged -- a tenant that
doesn't want a GenAI connection at all loses nothing. With one picked,
those same two signals are handed to it as context (webhook_service.
call_chat_completion's extra_user_context) instead of/alongside the
ticket alone, and its reply -- an actual hypothesis, not just a
restatement of the data -- is posted as the comment, with the raw
signals still appended underneath so nothing's a black box. A failed
call falls back to the plain deterministic comment rather than posting
nothing.

Since migration 0049 this same engine also reacts to one document
lifecycle trigger, document_pending_acknowledgment -- fired by
rain.modules.documents.service.request_acknowledgment the moment a
document's "who must acknowledge this" requirement is (re)set, the
document equivalent of a change ticket's approval starting. The
generic pieces below (_evaluate_and_fire, _rule_matches, _fire_rule,
_run_action) take either a Ticket or a Document (see TRIGGER_EVENTS for
which trigger_event goes with which); the ticket-only actions
(invoke_chat_completion, attach_document, attach_asset, mark_problematic,
analyze_root_cause, add_watcher -- see _TICKET_ONLY_ACTIONS) simply
report themselves not applicable when the matched record is a document
-- notify_slack/notify_email/webhook, the three that only ever needed a
placeholder dict, work for either kind unchanged."""
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
from rain.modules.tickets import rootcause, service as ticket_service
from rain.modules.tickets.notifications import (
    DEFAULT_EMAIL_MESSAGE_TEMPLATE,
    DEFAULT_MESSAGE_TEMPLATE,
    DEFAULT_SUBJECT_TEMPLATE,
    render_template,
    send_email,
    send_slack,
)
from rain.modules.webhooks import service as webhook_service

logger = logging.getLogger("rain.platform_events")

TRIGGER_EVENTS = [
    ("incident_created", "When an incident is created"),
    ("vulnerability_created", "When a vulnerability is created"),
    ("change_created", "When a change is created"),
    ("incident_closed", "When an incident is closed"),
    ("vulnerability_closed", "When a vulnerability is closed"),
    ("change_closed", "When a change is closed"),
    ("change_approved", "When a change is fully approved"),
    ("document_pending_acknowledgment", "When a document is pending your acknowledgment"),
]
MATCH_FIELDS = ["title", "description"]
# The last four only ever act on a Ticket -- see this module's own
# docstring. A rule using one of them against
# document_pending_acknowledgment still saves and still evaluates
# (match_field/pattern are equally meaningful against a Document's own
# title/description), it just skips that one action with a note in the
# trigger's logged summary rather than failing the whole rule.
ACTION_TYPES = [
    ("notify_slack", "Notify Slack"),
    ("notify_email", "Notify Email"),
    ("webhook", "Call a webhook"),
    ("invoke_chat_completion", "Invoke Chat Completions API"),
    ("attach_document", "Attach a document"),
    ("attach_asset", "Attach an asset"),
    ("mark_problematic", "Mark problematic"),
    ("analyze_root_cause", "Analyze root cause"),
    ("add_watcher", "Add a watcher"),
]

# The action types whose entire config is {"webhook_id": <WebhookConfig.
# id>} -- everywhere that shape gets built, displayed, or bundle-exported/
# imported treats them identically (only _run_action's own dispatch below
# actually differs between them, since a "webhook" call, an "invoke_chat_
# completion" call, and analyze_root_cause's optional AI narration do
# different things with the same referenced row). One tuple here instead
# of four call sites (tickets/router.py's config builder and display-label
# builder, config_bundle.py's export and import) each separately spelling
# out the list. analyze_root_cause differs from the other two in one way
# worth remembering: webhook_id is optional for it (no webhook picked ->
# rootcause.analyze's plain deterministic comment, same as always), while
# a "webhook"/"invoke_chat_completion" action with no webhook picked just
# fails at fire time -- see _run_action's own handling of each.
WEBHOOK_BACKED_ACTIONS = ("webhook", "invoke_chat_completion", "analyze_root_cause")

# One short sentence per action, shown under the "Add action" picker as
# it's selected (rule_form.html's ml_algorithm dropdown already does
# this for the same reason -- a value chosen from a name alone isn't
# always obvious what it actually does). Keyed separately from
# ACTION_TYPES itself rather than folded into a 3-tuple there, since
# dict(ACTION_TYPES) (this module's own _action_label, and the plain
# label lookup the Actions table renders with) needs 2-tuples.
ACTION_DESCRIPTIONS = {
    "notify_slack": "Send a message through a Slack notification channel.",
    "notify_email": "Send a message through an email notification channel.",
    "webhook": "Call one of this tenant's configured webhooks.",
    "invoke_chat_completion": "Send the ticket to a Chat Completions API webhook (OpenAI, Gemini, ...) and post its reply as a comment -- initial triage, a summary, whatever the webhook's own prompt asks for.",
    "attach_document": "Link a specific document to the ticket.",
    "attach_asset": "Set a specific asset as the ticket's affected asset, if it doesn't already have one.",
    "mark_problematic": "Flag the ticket problematic -- same as the ticket detail page's own quick action.",
    "analyze_root_cause": "Post the same repeat-occurrence and similar-past-ticket analysis the ticket detail page's own \"Analyze root cause\" button computes, as a comment -- optionally, pick a Chat Completions API webhook to have it narrate those same signals into an actual causal hypothesis instead of just reciting them.",
    "add_watcher": "Add a system user or a bare email as a watcher -- they start getting emailed on the ticket's activity.",
}

# rain.web.templates.base's nav_icon(name) macro -- one icon per action,
# shown on the "Add action" picker and on an existing action's own node
# in the rule detail page's flowchart. Reused from the app's existing
# icon set where a decent match already exists (mark_problematic ->
# "repeat", the same recurring-arrow icon a problematic ticket already
# shows elsewhere in the app; analyze_root_cause -> "search"; attach_
# document/attach_asset -> "file"/"server", already standing in for
# those record types on the sidebar) rather than adding a near-duplicate
# icon; "bell"/"mail"/"zap" were added to that shared set for the three
# with no existing equivalent.
ACTION_ICONS = {
    "notify_slack": "bell",
    "notify_email": "mail",
    "webhook": "zap",
    "invoke_chat_completion": "sparkles",
    "attach_document": "file",
    "attach_asset": "server",
    "mark_problematic": "repeat",
    "analyze_root_cause": "search",
    "add_watcher": "user",
}

_TRIGGER_BY_TICKET_TYPE = {
    "incident": "incident_created",
    "vulnerability": "vulnerability_created",
    "change": "change_created",
}
_TRIGGER_BY_TICKET_TYPE_CLOSED = {
    "incident": "incident_closed",
    "vulnerability": "vulnerability_closed",
    "change": "change_closed",
}


async def evaluate_ticket_created(db: AsyncSession, ticket: Ticket) -> None:
    """Called once, right after a ticket is committed (both the manual
    creation route and the syslog auto-promotion path go through
    rain.modules.tickets.service.create_ticket, so hooking it there covers
    both origins)."""
    trigger_event = _TRIGGER_BY_TICKET_TYPE.get(ticket.ticket_type)
    if trigger_event is not None:
        await _evaluate_and_fire(db, trigger_event, ticket)


async def evaluate_ticket_closed(db: AsyncSession, ticket: Ticket) -> None:
    """Called from rain.modules.tickets.service.update_status, once, on a
    transition into an is_closed status from one that wasn't -- see that
    function's own docstring for why "once" (a later closed -> closed
    move, e.g. Closed -> Cancelled, doesn't fire this again)."""
    trigger_event = _TRIGGER_BY_TICKET_TYPE_CLOSED.get(ticket.ticket_type)
    if trigger_event is not None:
        await _evaluate_and_fire(db, trigger_event, ticket)


async def evaluate_change_approved(db: AsyncSession, ticket: Ticket) -> None:
    """Called from rain.modules.tickets.service.decide_approval_step, once,
    the moment a change's approval flow clears its last step (mirrors
    _emit_syslog_on_full_approval, that function's own opt-in-per-flow
    sibling for the syslog/Event-Promotion-Policy pipeline instead of
    this one)."""
    await _evaluate_and_fire(db, "change_approved", ticket)


async def evaluate_document_pending_acknowledgment(db: AsyncSession, document: Document) -> None:
    """Called from rain.modules.documents.service.request_acknowledgment,
    once, each time a document's "who must acknowledge this" requirement
    is (re)set -- the document equivalent of evaluate_change_approved
    above: one entry point, fired at the one moment that matters, not on
    every read."""
    await _evaluate_and_fire(db, "document_pending_acknowledgment", document)


async def _evaluate_and_fire(db: AsyncSession, trigger_event: str, record: Ticket | Document) -> None:
    """Shared by every evaluate_* entry point above -- load this trigger's
    active rules, run every match, fire every one that matches (not just
    the first). `record` is whichever kind of row this trigger_event is
    actually about -- a Ticket for every trigger except
    document_pending_acknowledgment, which is about a Document instead.
    Never raises -- a broken rule/action must not take down whatever
    lifecycle step called this."""
    try:
        stmt = (
            select(PlatformEventRule)
            .where(PlatformEventRule.is_active.is_(True), PlatformEventRule.trigger_event == trigger_event)
            .options(selectinload(PlatformEventRule.actions))
            .order_by(PlatformEventRule.sort_order)
        )
        rules = list((await db.execute(stmt)).scalars())
    except Exception:
        logger.exception("failed to load platform event rules (%s) for %s %s", trigger_event, type(record).__name__, record.id)
        return

    for rule in rules:
        try:
            if _rule_matches(rule, record):
                await _fire_rule(db, rule, record)
        except Exception:
            logger.exception("platform event rule %s failed for %s %s", rule.id, type(record).__name__, record.id)


def _rule_matches(rule: PlatformEventRule, record: Ticket | Document) -> bool:
    value = getattr(record, rule.match_field, None)
    if not value:
        return False
    try:
        return re.search(rule.pattern, value) is not None
    except re.error:
        return False


async def _fire_rule(db: AsyncSession, rule: PlatformEventRule, record: Ticket | Document) -> None:
    outcomes: list[str] = []
    for action in rule.actions:
        try:
            outcomes.append(await _run_action(db, action, record))
        except Exception as exc:
            logger.exception("platform event action %s (rule %s) failed for %s %s", action.id, rule.id, type(record).__name__, record.id)
            outcomes.append(f"{_action_label(action.action_type)}: failed ({exc})")

    summary = "; ".join(outcomes) if outcomes else "matched (no actions configured)"
    is_ticket = isinstance(record, Ticket)
    db.add(
        PlatformEventTrigger(
            rule_id=rule.id,
            rule_name=rule.name,
            ticket_id=record.id if is_ticket else None,
            document_id=None if is_ticket else record.id,
            summary=summary,
        )
    )
    if is_ticket:
        # Also onto the ticket's own unified activity feed, not just the
        # rule's trigger-history table -- a rule firing is a system-
        # caused change to this specific ticket and belongs alongside
        # status/severity/etc changes, not only visible by navigating to
        # the rule. Documents have no equivalent unified activity feed,
        # so a document-triggered rule's firing is only visible via
        # platform_event_triggers itself for now.
        await ticket_service.log_field_change(db, record.id, "platform_rule", rule.name, summary, commit=False)
    await db.commit()


def _action_label(action_type: str) -> str:
    return dict(ACTION_TYPES).get(action_type, action_type)


def _record_label(record: Ticket | Document) -> str:
    return record.ticket_number if isinstance(record, Ticket) else record.doc_number


def _ticket_placeholders(ticket: Ticket) -> dict[str, str]:
    """The macro set available in a webhook payload_template or a
    notification channel's message/subject_template -- {{ticket_number}},
    {{title}}, {{description}}, etc. One definition shared by both
    callers below so the two don't drift out of sync on what's available."""
    return {
        "ticket_number": ticket.ticket_number,
        "ticket_type": ticket.ticket_type,
        "title": ticket.title,
        "description": ticket.description or "",
        "severity": ticket.severity,
        "status": ticket.status,
    }


def _document_placeholders(document: Document) -> dict[str, str]:
    """The document-triggered equivalent of _ticket_placeholders --
    {{doc_number}}, {{title}}, {{description}}. Smaller than a ticket's
    own set: a document has no severity/status to offer."""
    return {
        "doc_number": document.doc_number,
        "title": document.title,
        "description": document.description or "",
    }


def _placeholders(record: Ticket | Document) -> dict[str, str]:
    return _ticket_placeholders(record) if isinstance(record, Ticket) else _document_placeholders(record)


# Ticket-only -- see this module's own docstring. Guarded upfront in
# _run_action rather than duplicated into each branch's own isinstance
# check below. invoke_chat_completion joins this set (unlike its sibling
# "webhook", which works for either) because it always builds its user
# message from a ticket's own fields (rain.modules.webhooks.service.
# _ticket_payload_text) and always posts its reply back as a ticket
# comment -- neither has a document equivalent.
_TICKET_ONLY_ACTIONS = {
    "invoke_chat_completion", "attach_document", "attach_asset", "mark_problematic", "analyze_root_cause", "add_watcher"
}


async def _run_action(db: AsyncSession, action: PlatformEventAction, record: Ticket | Document) -> str:
    config = action.config or {}
    label = _action_label(action.action_type)

    if action.action_type in _TICKET_ONLY_ACTIONS and not isinstance(record, Ticket):
        return f"{label}: only applies to a ticket-triggered rule, skipped for {_record_label(record)}"

    if action.action_type in ("notify_slack", "notify_email"):
        channel_id = config.get("channel_id")
        channel = await db.get(NotificationChannel, channel_id) if channel_id else None
        if channel is None:
            return f"{label}: channel no longer exists"
        channel_config = decrypt_json(channel.config_encrypted)
        placeholders = _placeholders(record)

        # Dispatched on the *channel's own* channel_type, not the action's
        # -- a channel is free to be any of the three types regardless of
        # which of "Notify Slack"/"Notify Email" a rule author picked to
        # add the action (both share the same channel picker, see
        # platform_event_detail.html), so this is the one place that
        # actually decides how the message goes out.
        if channel.channel_type == "webhook":
            webhook_id = channel_config.get("webhook_id")
            webhook = await db.get(WebhookConfig, webhook_id) if webhook_id else None
            if webhook is None:
                return f"{label}: channel's webhook no longer exists"
            result = await webhook_service.call_webhook(webhook, placeholders)
            if not result.success and webhook.alert_on_failure:
                await webhook_service.alert_webhook_failure(
                    db, webhook, result, context=f"notification channel '{channel.name}' on {_record_label(record)}"
                )
            if result.error:
                return f"{label}: {channel.name} -> {result.error}"
            return f"{label}: {channel.name} -> HTTP {result.status_code}"

        if channel.channel_type == "slack":
            webhook_url = channel_config.get("webhook_url")
            if not webhook_url:
                return f"{label}: channel has no webhook URL"
            text = render_template(channel.message_template or DEFAULT_MESSAGE_TEMPLATE, placeholders)
            await send_slack(webhook_url, text)
            return f"{label}: sent to '{channel.name}'"

        recipients = channel_config.get("recipients", [])
        if not recipients:
            return f"{label}: channel has no recipients"
        subject = render_template(channel.subject_template or DEFAULT_SUBJECT_TEMPLATE, placeholders)
        body = render_template(channel.message_template or DEFAULT_EMAIL_MESSAGE_TEMPLATE, placeholders)
        await send_email(recipients, subject, body)
        return f"{label}: sent to '{channel.name}'"

    if action.action_type == "webhook":
        webhook_id = config.get("webhook_id")
        webhook = await db.get(WebhookConfig, webhook_id) if webhook_id else None
        if webhook is None:
            return f"{label}: webhook no longer exists"
        placeholders = _placeholders(record)
        result = await webhook_service.call_webhook(webhook, placeholders)
        if not result.success and webhook.alert_on_failure:
            await webhook_service.alert_webhook_failure(
                db, webhook, result, context=f"Platform Response Rule action on {_record_label(record)}"
            )
        if result.error:
            return f"{label}: {webhook.name} -> {result.error}"
        return f"{label}: {webhook.name} -> HTTP {result.status_code}"

    # Every action from here down is ticket-only (see _TICKET_ONLY_ACTIONS
    # above, already guarded) -- `record` is a Ticket for the rest of
    # this function.
    ticket = record

    if action.action_type == "invoke_chat_completion":
        webhook_id = config.get("webhook_id")
        webhook = await db.get(WebhookConfig, webhook_id) if webhook_id else None
        if webhook is None:
            return f"{label}: webhook no longer exists"
        if webhook.kind != "chat_completions":
            return f"{label}: '{webhook.name}' isn't a Chat Completions API webhook"
        result = await webhook_service.call_chat_completion(db, webhook, ticket)
        if not result.success and webhook.alert_on_failure:
            await webhook_service.alert_webhook_failure(
                db, webhook, result, context=f"Platform Response Rule action on {_record_label(record)}"
            )
        if not result.success:
            return f"{label}: {webhook.name} -> {result.error or f'HTTP {result.status_code}'}"
        # Posted the same way analyze_root_cause posts its own analysis
        # above -- a system comment (author_user_id=None), landing in the
        # ticket's own activity feed. Firing this rule on a *_created
        # trigger (the common case for "initial triage") means this
        # comment goes up right after the ticket itself does, before a
        # human's had the chance to comment at all -- which is what makes
        # it read as the ticket's first update rather than something
        # bolted on afterward; nothing here enforces an ordinal position,
        # the trigger you pick is what makes it "first" in practice.
        await ticket_service.add_comment(db, ticket.id, author_user_id=None, body=result.reply)
        return f"{label}: posted a comment via {webhook.name}"

    if action.action_type == "attach_document":
        document_id = config.get("document_id")
        document = await db.get(Document, document_id) if document_id else None
        if document is None:
            return f"{label}: document no longer exists"
        _, created = await document_service.add_link(db, document.id, "ticket", ticket.id, created_by=None)
        if created:
            # Also on the Activity feed, not just this rule-trigger log --
            # a link is a change to the ticket regardless of what caused it.
            await ticket_service.log_field_change(
                db, ticket.id, "document", None, f"{document.doc_number}: {document.title}"
            )
            return f"{label}: linked {document.doc_number}"
        return f"{label}: {document.doc_number} already linked"

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

    if action.action_type == "mark_problematic":
        if ticket.is_problematic:
            return f"{label}: already problematic"
        await ticket_service.update_problematic(db, ticket, True)
        return f"{label}: done"

    if action.action_type == "analyze_root_cause":
        # Same two signals (repeat-occurrence pattern, similar past
        # closed tickets) the on-demand "Analyze root cause" button
        # computes -- see rootcause's own docstring. None means neither
        # signal turned anything up, same "skip rather than post a
        # content-free comment" rule the button's own preview step
        # follows. Computed before touching the optional webhook below
        # so a rule with no webhook configured (the common case) never
        # pays for a lookup it doesn't need.
        deterministic = await rootcause.analyze(db, ticket)
        if not deterministic:
            return f"{label}: nothing to add"

        webhook_id = config.get("webhook_id")
        webhook = await db.get(WebhookConfig, webhook_id) if webhook_id else None
        if webhook_id and webhook is None:
            return f"{label}: webhook no longer exists"
        if webhook is not None and webhook.kind != "chat_completions":
            return f"{label}: '{webhook.name}' isn't a Chat Completions API webhook"

        if webhook is None:
            await ticket_service.add_comment(db, ticket.id, author_user_id=None, body=deterministic)
            return f"{label}: posted a comment"

        result = await webhook_service.call_chat_completion(db, webhook, ticket, extra_user_context=deterministic)
        if not result.success:
            if webhook.alert_on_failure:
                await webhook_service.alert_webhook_failure(
                    db, webhook, result, context=f"Platform Response Rule action on {_record_label(record)}"
                )
            # The deterministic signals are still real and still useful
            # even though narrating them into a hypothesis failed --
            # post them rather than posting nothing.
            await ticket_service.add_comment(db, ticket.id, author_user_id=None, body=deterministic)
            return f"{label}: AI narration via {webhook.name} failed ({result.error}) -- posted the deterministic comment instead"

        analysis = (
            f"Root cause assistance (AI-narrated via {webhook.name}) - hypothesis based on the "
            f"signals below, not a determined cause:\n\n{result.reply}\n\n---\nSignals used:\n{deterministic}"
        )
        await ticket_service.add_comment(db, ticket.id, author_user_id=None, body=analysis)
        return f"{label}: posted an AI-narrated comment via {webhook.name}"

    if action.action_type == "add_watcher":
        email = (config.get("email") or "").strip()
        user_id = config.get("user_id")
        if email:
            await ticket_service.add_watcher_by_email(db, ticket.id, email)
            return f"{label}: {email}"
        if user_id:
            await ticket_service.add_watcher(db, ticket.id, user_id)
            return f"{label}: user #{user_id}"
        return f"{label}: no email or user configured"

    return f"{label}: unknown action type"
