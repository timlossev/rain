"""Centrally-configured outbound webhooks (Admin > Webhooks). One
WebhookConfig definition, called from anywhere that needs to fire a
webhook -- Platform Response Rules' "webhook" action and a Document's
"populate from webhook" setting are the two callers today -- instead of
each place inlining its own URL/headers/payload/timeout handling.

call_chat_completion (kind="chat_completions" only) is a second,
separate call path rather than a branch inside call_webhook -- the
request/response shape isn't a user-authored template, it's the fixed
{model, messages: [...]} -> {choices: [{message: {content}}]} contract
every OpenAI-compatible Chat Completions API (OpenAI itself, Gemini's
own compatibility endpoint, ...) already speaks, so there's nothing
call_webhook's own payload_template/raw-body-passthrough logic would
add here."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rain.core.url_safety import check_outbound_url
from rain.db.tenant_models import SyslogEvent, Ticket, TicketFieldValue, WebhookConfig
from rain.modules.tickets import rules as ticket_rules

logger = logging.getLogger("rain.webhooks")


def _json_escape(value: str) -> str:
    """Escape a raw string for embedding inside a JSON string literal in
    a payload_template (the surrounding quotes are the template's own).
    json.dumps of a plain string always yields "escaped text" -- strip
    that outer quote pair since the template already supplies its own."""
    return json.dumps(value)[1:-1]


def render_payload(template: str, placeholders: dict[str, str]) -> str:
    """Double-brace ({{key}}) substitution -- Mustache/Jinja-style rather
    than str.format()'s single-brace: the payload itself is JSON, which
    is full of single braces str.format() would misparse as fields
    (confirmed via a real webhook action run: KeyError on the JSON
    object's own '{')."""
    rendered = template
    for key, value in placeholders.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", _json_escape(str(value)))
    return rendered


@dataclass
class WebhookResult:
    status_code: int | None
    success: bool
    body: str
    error: str | None = None


def _parse_success_codes(raw: str) -> set[int]:
    codes = {int(part.strip()) for part in raw.split(",") if part.strip().isdigit()}
    return codes or {200}


async def call_webhook(config: WebhookConfig, placeholders: dict[str, str] | None = None) -> WebhookResult:
    """Never raises -- both callers (a rule firing, a document refresh)
    treat a failed call as a logged/displayed outcome, not something
    that should propagate and take down whatever triggered it."""
    unsafe_reason = await check_outbound_url(config.url)
    if unsafe_reason is not None:
        logger.warning("webhook '%s' blocked -- %s", config.name, unsafe_reason)
        return WebhookResult(status_code=None, success=False, body="", error=unsafe_reason)

    method = (config.http_method or "POST").upper()
    headers = dict(config.headers or {})
    success_codes = _parse_success_codes(config.success_codes)

    request_kwargs: dict = {}
    if method in ("POST", "PUT", "PATCH") and config.payload_template:
        rendered = render_payload(config.payload_template, placeholders or {})
        try:
            payload = json.loads(rendered)
        except ValueError:
            payload = None
        if payload is not None:
            request_kwargs["json"] = payload
        else:
            request_kwargs["content"] = rendered
            headers.setdefault("Content-Type", "application/json")

    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds or 10) as client:
            resp = await client.request(method, config.url, headers=headers, **request_kwargs)
        success = resp.status_code in success_codes
        if success:
            logger.info("webhook '%s' called -- %s %s -> HTTP %s", config.name, method, config.url, resp.status_code)
        else:
            # Previously no logging here at all -- a webhook returning
            # something other than its configured success_codes (a
            # revoked API token, a 500 on the receiving end, ...) was
            # only ever visible by way of alert_webhook_failure(), and
            # only when that specific webhook has alert_on_failure
            # turned on. This fires regardless, so it's not only in the
            # container log stream when someone happened to opt into
            # the DB-recorded alert too.
            logger.warning(
                "webhook '%s' returned an unexpected status -- %s %s -> HTTP %s (expected one of %s)",
                config.name, method, config.url, resp.status_code, sorted(success_codes),
            )
        return WebhookResult(status_code=resp.status_code, success=success, body=resp.text)
    except httpx.HTTPError as exc:
        logger.warning("webhook '%s' call failed -- %s %s -> %s", config.name, method, config.url, exc)
        return WebhookResult(status_code=None, success=False, body="", error=str(exc))


async def alert_webhook_failure(
    db: AsyncSession, webhook: WebhookConfig, result: WebhookResult | ChatCompletionResult, *, context: str
) -> None:
    """Called by a caller of call_webhook *or* call_chat_completion when
    result.success is False and webhook.alert_on_failure is set --
    synthesizes a SyslogEvent and runs it through the same rule engine
    real syslog traffic goes through
    (rain.modules.tickets.rules), same pattern as rain.modules.calendar.
    sweep's syslog bridge and Document's alert_on_change, so a webhook
    that's stopped responding can auto-file a ticket the same way any
    other monitored condition can."""
    detail = result.error or f"HTTP {result.status_code}"
    event = SyslogEvent(
        host="webhooks",
        program=webhook.name,
        facility=None,
        severity=3,  # error
        message=f"Webhook '{webhook.name}' failed ({context}): {detail}",
        raw=f"webhook_config #{webhook.id} call failure -- {context}",
    )
    db.add(event)
    await db.commit()
    await ticket_rules.evaluate_and_promote(db, event)


@dataclass
class ChatCompletionResult:
    status_code: int | None
    success: bool
    reply: str
    error: str | None = None


def _ticket_payload_text(ticket: Ticket) -> str:
    """The "user" message content for a chat-completions call -- plain
    readable text (not JSON: this is going to a language model, which
    reads prose at least as well as a data structure, and prose doesn't
    need a schema the model has to guess isn't there) covering
    everything about the ticket a human triaging it would look at
    first: the fixed fields, its asset if linked, and every tenant
    custom field value."""
    lines = [
        f"Ticket: {ticket.ticket_number}",
        f"Type: {ticket.ticket_type}",
        f"Title: {ticket.title}",
        f"Severity: {ticket.severity}",
        f"Status: {ticket.status}",
    ]
    if ticket.asset is not None:
        lines.append(f"Asset: {ticket.asset.name}")
    lines.append("")
    lines.append("Description:")
    lines.append(ticket.description or "(none)")
    field_values = [fv for fv in ticket.field_values if fv.field is not None]
    if field_values:
        lines.append("")
        lines.append("Custom fields:")
        lines.extend(f"- {fv.field.label}: {fv.value}" for fv in field_values)
    return "\n".join(lines)


async def call_chat_completion(
    db: AsyncSession, config: WebhookConfig, ticket: Ticket, *, extra_user_context: str | None = None
) -> ChatCompletionResult:
    """kind="chat_completions" only. Builds the system message from
    chat_system_prompt and/or chat_memory_document_id's own text (the
    "shared project memory / client-wide context" -- read the same way
    the jq-transform ruleset picker already reads a Document, plain
    text regardless of body_kind), the user message from the calling
    ticket's own content plus the full text of every document linked to
    it (same Links tab a human triaging the ticket would open), POSTs
    {model, messages} to config.url, and pulls the reply out of the
    standard choices[0].message.content shape every OpenAI-compatible
    provider returns it in. Never raises, same contract as call_webhook
    -- a caller (a Platform Response Rule action) treats a failure as a
    logged/reported outcome, not something to propagate.

    extra_user_context, when given, is appended to the user message
    after the ticket payload -- e.g. the Platform Response Rule
    "Analyze root cause" action's optional AI-narrated mode hands in
    rootcause.analyze's own deterministic signals (repeat-occurrence
    pattern, similar closed tickets) here, so the model reasons over
    real data already on hand instead of just the ticket text alone."""
    from rain.modules.documents import service as document_service  # deferred: documents.service imports this module

    unsafe_reason = await check_outbound_url(config.url)
    if unsafe_reason is not None:
        logger.warning("chat completions webhook '%s' blocked -- %s", config.name, unsafe_reason)
        return ChatCompletionResult(status_code=None, success=False, reply="", error=unsafe_reason)

    stmt = (
        select(Ticket)
        .where(Ticket.id == ticket.id)
        .options(selectinload(Ticket.asset), selectinload(Ticket.field_values).selectinload(TicketFieldValue.field))
    )
    full_ticket = (await db.execute(stmt)).scalar_one_or_none() or ticket

    system_parts = [config.chat_system_prompt.strip()] if config.chat_system_prompt else []
    if config.chat_memory_document_id:
        memory_text = await document_service.get_document_text_body(db, config.chat_memory_document_id)
        if memory_text:
            system_parts.append(memory_text.strip())
    system_content = "\n\n".join(system_parts) or "You are a helpful IT service management assistant."

    user_content = _ticket_payload_text(full_ticket)
    # Linked documents (runbooks, inventory exports, past incident write-
    # ups -- whatever's been attached to this ticket) go in the user
    # message too, same "prose, not a caller-authored schema" reasoning
    # _ticket_payload_text's own docstring gives for the ticket fields
    # themselves -- the model gets the same context a human triaging this
    # ticket would open the Links tab to read, not just the ticket text
    # alone.
    links = await document_service.links_for(db, "ticket", full_ticket.id)
    for link in links:
        doc_text = await document_service.get_document_text_body(db, link.document_id)
        if doc_text and doc_text.strip():
            user_content += f"\n\nLinked document {link.document.doc_number} ({link.document.title}):\n{doc_text.strip()}"
    if extra_user_context:
        user_content += "\n\n" + extra_user_context

    body = {
        "model": config.chat_model or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
    }
    headers = dict(config.headers or {})
    headers.setdefault("Content-Type", "application/json")
    success_codes = _parse_success_codes(config.success_codes)

    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds or 10) as client:
            resp = await client.post(config.url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        logger.warning("chat completions webhook '%s' call failed -- %s", config.name, exc)
        return ChatCompletionResult(status_code=None, success=False, reply="", error=str(exc))

    if resp.status_code not in success_codes:
        logger.warning("chat completions webhook '%s' returned HTTP %s", config.name, resp.status_code)
        return ChatCompletionResult(
            status_code=resp.status_code, success=False, reply="", error=f"HTTP {resp.status_code}: {resp.text[:500]}"
        )

    try:
        reply = resp.json()["choices"][0]["message"]["content"]
        # content is nullable in the Chat Completions response shape (a
        # tool-call-only reply, or a content-filtered one, both return it
        # as JSON null rather than omitting the key) -- a bare dict
        # lookup doesn't raise for that, so it has to be checked
        # explicitly rather than left for .strip() below to blow up on.
        if not isinstance(reply, str):
            raise TypeError(f"choices[0].message.content was {reply!r}, not a string")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("chat completions webhook '%s' returned an unparseable response -- %s", config.name, exc)
        return ChatCompletionResult(
            status_code=resp.status_code, success=False, reply="", error=f"unparseable response: {exc}"
        )

    logger.info("chat completions webhook '%s' called -- HTTP %s", config.name, resp.status_code)
    return ChatCompletionResult(status_code=resp.status_code, success=True, reply=reply.strip())


async def get_webhook(db: AsyncSession, webhook_id: int) -> WebhookConfig | None:
    return await db.get(WebhookConfig, webhook_id)


async def get_webhooks(db: AsyncSession, webhook_ids: set[int]) -> dict[int, WebhookConfig]:
    """Batched form of get_webhook -- one query for several ids at once
    (rain.modules.documents.service.refresh_many_from_webhook), rather
    than N sequential round-trips before the actual, concurrency-worthy
    webhook calls even start."""
    if not webhook_ids:
        return {}
    result = await db.execute(select(WebhookConfig).where(WebhookConfig.id.in_(webhook_ids)))
    return {w.id: w for w in result.scalars()}


async def list_webhooks(db: AsyncSession) -> list[WebhookConfig]:
    result = await db.execute(select(WebhookConfig).order_by(WebhookConfig.name))
    return list(result.scalars())


async def create_webhook(
    db: AsyncSession,
    *,
    name: str,
    kind: str = "generic",
    url: str,
    http_method: str,
    headers: dict,
    payload_template: str,
    timeout_seconds: int,
    success_codes: str,
    alert_on_failure: bool = False,
    chat_model: str | None = None,
    chat_system_prompt: str | None = None,
    chat_memory_document_id: int | None = None,
    created_by: int | None,
) -> WebhookConfig:
    webhook = WebhookConfig(
        name=name,
        kind=kind,
        url=url,
        http_method=http_method,
        headers=headers,
        payload_template=payload_template,
        timeout_seconds=timeout_seconds,
        success_codes=success_codes,
        alert_on_failure=alert_on_failure,
        chat_model=chat_model,
        chat_system_prompt=chat_system_prompt,
        chat_memory_document_id=chat_memory_document_id,
        created_by=created_by,
    )
    db.add(webhook)
    await db.commit()
    return webhook


async def update_webhook(
    db: AsyncSession,
    webhook: WebhookConfig,
    *,
    name: str,
    kind: str = "generic",
    url: str,
    http_method: str,
    headers: dict,
    payload_template: str,
    timeout_seconds: int,
    success_codes: str,
    alert_on_failure: bool = False,
    chat_model: str | None = None,
    chat_system_prompt: str | None = None,
    chat_memory_document_id: int | None = None,
) -> None:
    webhook.name = name
    webhook.kind = kind
    webhook.url = url
    webhook.http_method = http_method
    webhook.headers = headers
    webhook.payload_template = payload_template
    webhook.timeout_seconds = timeout_seconds
    webhook.success_codes = success_codes
    webhook.alert_on_failure = alert_on_failure
    webhook.chat_model = chat_model
    webhook.chat_system_prompt = chat_system_prompt
    webhook.chat_memory_document_id = chat_memory_document_id
    await db.commit()


async def delete_webhook(db: AsyncSession, webhook: WebhookConfig) -> None:
    await db.delete(webhook)
    await db.commit()


def parse_headers_text(text: str) -> dict[str, str]:
    """The admin form edits headers as plain "Name: value" lines (one per
    header) rather than raw JSON -- friendlier to hand-type, and this is
    the only place that shape needs parsing."""
    headers: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key:
            headers[key] = value.strip()
    return headers


def format_headers_text(headers: dict[str, str] | None) -> str:
    return "\n".join(f"{k}: {v}" for k, v in (headers or {}).items())
