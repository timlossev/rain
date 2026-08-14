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
    except Exception:
        logger.exception("failed to send email notification to %s", recipients)


async def send_slack(webhook_url: str, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json={"text": text})
    except Exception:
        logger.exception("failed to send Slack notification")
