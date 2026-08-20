"""Low-level email + Slack senders. Who gets notified, and under what
condition, is decided by Platform Event rules
(rain.modules.tickets.platform_events) -- this module just knows how to
actually deliver a message once a rule's action decides to. The SMTP
relay is instance-wide (control.global_config, set once by internal_admin
in Admin > SMTP); channel config (recipients / webhook URL) is per-tenant
(rain.db.tenant_models.NotificationChannel).

There used to also be an unconditional "notify on every ticket of this
type" path here (notify_ticket_created(), run on every ticket creation
regardless of any rule), driven by NotificationChannel.notify_on_incident/
notify_on_vulnerability. It was removed: Platform Events already lets an
admin express the same "always notify" behavior explicitly (a rule with
pattern ".*" and a notify_slack/notify_email action), so keeping both
meant every ticket could double-notify through two independent, easily
out-of-sync code paths for no added capability. See migration 0006."""
from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Any

import aiosmtplib
import httpx

from rain.core.config_store import config_store
from rain.core.crypto import decrypt_json

logger = logging.getLogger("rain.notifications")

# Used when a channel's own message_template/subject_template is blank --
# NotificationChannel ships with empty templates (migration 0024), not
# these baked into the column default, so "never customized" and
# "deliberately cleared" both fall back the same simple way rather than
# needing an explicit sentinel.
DEFAULT_MESSAGE_TEMPLATE = "*{{ticket_number}}* ({{severity}}) {{title}}"
DEFAULT_EMAIL_MESSAGE_TEMPLATE = "{{ticket_number}} ({{severity}}) created.\n\n{{description}}"
DEFAULT_SUBJECT_TEMPLATE = "[RAIN] {{ticket_number}}: {{title}}"


def render_template(template: str, placeholders: dict[str, str]) -> str:
    """Plain double-brace ({{key}}) substitution for a notification
    channel's message/subject template -- no JSON-escaping (unlike
    rain.modules.webhooks.service.render_payload, which renders into a
    JSON payload body); this is human-readable Slack/email text."""
    rendered = template
    for key, value in placeholders.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


async def send_email(recipients: list[str], subject: str, body: str) -> None:
    host = config_store.get("smtp_host")
    if not host or not recipients:
        # Previously a bare, silent return -- indistinguishable in the
        # logs from this having actually sent. A caller that already
        # checked config_store itself before calling (there isn't one
        # today) would find this redundant; every actual caller doesn't,
        # so this is the only place that would ever say so.
        logger.warning(
            "email notification skipped (%s) -- subject=%r",
            "no SMTP relay configured" if not host else "no recipients",
            subject,
        )
        return

    message = EmailMessage()
    message["From"] = config_store.get("smtp_from_address") or "rain@localhost"
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    kwargs: dict[str, Any] = {
        "hostname": host,
        "port": int(config_store.get("smtp_port") or 587),
        "use_tls": bool(config_store.get("smtp_use_tls", True)),
    }
    username = config_store.get("smtp_username")
    encrypted_password = config_store.get("smtp_password_encrypted")
    if username:
        kwargs["username"] = username
        kwargs["password"] = decrypt_json(bytes.fromhex(encrypted_password)) if encrypted_password else ""

    try:
        await aiosmtplib.send(message, **kwargs)
        logger.info("email notification sent to %s -- subject=%r", recipients, subject)
    except Exception:
        logger.exception("failed to send email notification to %s", recipients)


async def send_test_email(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    use_tls: bool,
    from_address: str,
    to_address: str,
) -> tuple[bool, str]:
    """Admin > SMTP's "Send test email" button -- unlike send_email above,
    this takes the relay settings as plain arguments instead of reading
    them from config_store, so it tests exactly what's currently typed
    into the form (including an as-yet-unsaved change), not whatever was
    last saved. Never raises: returns (False, <reason>) on any failure --
    connection refused, auth rejected, TLS negotiation failure, whatever
    aiosmtplib surfaces -- so the admin route can show it inline rather
    than a 500."""
    message = EmailMessage()
    message["From"] = from_address or "rain@localhost"
    message["To"] = to_address
    message["Subject"] = "RAIN: SMTP relay test"
    message.set_content(
        "This is a test email from RAIN's Admin > SMTP Relay page.\n\n"
        "If you're reading this, outbound email is configured correctly."
    )
    kwargs: dict[str, Any] = {"hostname": host, "port": port, "use_tls": use_tls}
    if username:
        kwargs["username"] = username
        kwargs["password"] = password
    try:
        await aiosmtplib.send(message, **kwargs)
        logger.info("SMTP test email sent to %s via %s:%s", to_address, host, port)
        return True, f"Test email sent to {to_address}."
    except Exception as exc:
        logger.warning("SMTP test email to %s via %s:%s failed: %s", to_address, host, port, exc)
        return False, str(exc)


async def send_slack(webhook_url: str, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json={"text": text})
        # httpx only raises for a network-level failure (DNS, connection
        # refused, timeout) -- an HTTP-level error response (404 for a
        # revoked webhook, 500 from Slack's own side) doesn't raise on
        # its own and, before this, went completely unchecked: a dead
        # webhook URL looked identical to a real success.
        if resp.status_code >= 400:
            logger.warning("Slack notification rejected -- HTTP %s: %s", resp.status_code, resp.text[:300])
        else:
            logger.info("Slack notification sent (HTTP %s)", resp.status_code)
    except Exception:
        logger.exception("failed to send Slack notification")
