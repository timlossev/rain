"""Email + Slack notification on ticket creation. The SMTP relay is
instance-wide (control.global_config, set once by internal_admin in
Admin > SMTP); who gets notified is per-tenant
(rain.db.tenant_models.NotificationChannel)."""
from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Any

import aiosmtplib
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.config_store import config_store
from rain.core.crypto import decrypt_json
from rain.db.tenant_models import NotificationChannel, Ticket

logger = logging.getLogger("rain.notifications")


async def _send_email(recipients: list[str], subject: str, body: str) -> None:
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


async def _send_slack(webhook_url: str, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json={"text": text})
    except Exception:
        logger.exception("failed to send Slack notification")


async def notify_ticket_created(db: AsyncSession, ticket: Ticket) -> None:
    result = await db.execute(select(NotificationChannel).where(NotificationChannel.is_enabled.is_(True)))
    channels = list(result.scalars())
    if not channels:
        return

    flag = "notify_on_incident" if ticket.ticket_type == "incident" else "notify_on_vulnerability"
    subject = f"[RAIN] {ticket.ticket_number}: {ticket.title}"
    body = f"{ticket.ticket_number} ({ticket.severity}) created.\n\n{ticket.description or ''}"

    for channel in channels:
        if not getattr(channel, flag):
            continue
        config = decrypt_json(channel.config_encrypted)
        if channel.channel_type == "email":
            await _send_email(config.get("recipients", []), subject, body)
        elif channel.channel_type == "slack":
            webhook_url = config.get("webhook_url")
            if webhook_url:
                await _send_slack(webhook_url, f"*{ticket.ticket_number}* ({ticket.severity}) {ticket.title}")
