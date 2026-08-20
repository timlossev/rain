"""Centrally-configured outbound webhooks (Admin > Webhooks). One
WebhookConfig definition, called from anywhere that needs to fire a
webhook -- Platform Response Rules' "webhook" action and a Document's
"populate from webhook" setting are the two callers today -- instead of
each place inlining its own URL/headers/payload/timeout handling."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import SyslogEvent, WebhookConfig
from rain.modules.tickets import correlation as ticket_correlation
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


async def alert_webhook_failure(db: AsyncSession, webhook: WebhookConfig, result: WebhookResult, *, context: str) -> None:
    """Called by a caller of call_webhook when result.success is False and
    webhook.alert_on_failure is set -- synthesizes a SyslogEvent and runs
    it through the same rule engine real syslog traffic goes through
    (rain.modules.tickets.rules/correlation), same pattern as
    rain.modules.calendar.sweep's syslog bridge and Document's
    alert_on_change, so a webhook that's stopped responding can auto-file
    a ticket the same way any other monitored condition can."""
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
    matched_rule = await ticket_rules.find_matching_rule(db, event)
    if matched_rule is not None:
        await ticket_rules.apply_rule(db, matched_rule, event)
    await ticket_correlation.evaluate_correlation_rules(db, event)


async def get_webhook(db: AsyncSession, webhook_id: int) -> WebhookConfig | None:
    return await db.get(WebhookConfig, webhook_id)


async def list_webhooks(db: AsyncSession) -> list[WebhookConfig]:
    result = await db.execute(select(WebhookConfig).order_by(WebhookConfig.name))
    return list(result.scalars())


async def create_webhook(
    db: AsyncSession,
    *,
    name: str,
    url: str,
    http_method: str,
    headers: dict,
    payload_template: str,
    timeout_seconds: int,
    success_codes: str,
    alert_on_failure: bool = False,
    created_by: int | None,
) -> WebhookConfig:
    webhook = WebhookConfig(
        name=name,
        url=url,
        http_method=http_method,
        headers=headers,
        payload_template=payload_template,
        timeout_seconds=timeout_seconds,
        success_codes=success_codes,
        alert_on_failure=alert_on_failure,
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
    url: str,
    http_method: str,
    headers: dict,
    payload_template: str,
    timeout_seconds: int,
    success_codes: str,
    alert_on_failure: bool = False,
) -> None:
    webhook.name = name
    webhook.url = url
    webhook.http_method = http_method
    webhook.headers = headers
    webhook.payload_template = payload_template
    webhook.timeout_seconds = timeout_seconds
    webhook.success_codes = success_codes
    webhook.alert_on_failure = alert_on_failure
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
