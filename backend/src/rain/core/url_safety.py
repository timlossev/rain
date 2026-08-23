"""Guards outbound HTTP calls this app makes on a tenant's behalf --
webhooks (rain.modules.webhooks.service.call_webhook) and Slack
notifications (rain.modules.tickets.notifications.send_slack) -- against
SSRF.

RAIN is explicitly built to run air-gapped, reaching a tenant's own
internal network -- an on-prem monitoring tool, an internal API, a
self-hosted chat server -- is the normal, intended case for a webhook
here, not an attack. A private/RFC1918 address (10.0.0.0/8,
172.16.0.0/12, 192.168.0.0/16) is explicitly ALLOWED. What's blocked
instead is the handful of address ranges that are never a legitimate
webhook target in ANY deployment, air-gapped or not: loopback (would
reach this app's own container instead of whatever host the webhook
claims to target) and link-local, which is what actually covers a
cloud metadata endpoint (169.254.169.254 on AWS/GCP, the Azure
equivalent) -- the concrete, high-value credential-theft target this
exists for.

This validates the *scheme* and the *resolved IP* at call time (not
just when the URL is saved), which is what actually matters -- catching
a URL that looked fine when an admin saved it but now resolves
somewhere this doesn't allow. It is not a defense against a determined
DNS-rebinding attack (the resolution here and httpx's own resolution a
moment later are two separate lookups, so a nameserver that flips
answers between them could still slip a blocked address past this check
into the real connection) -- closing that gap fully needs a custom
transport that connects to the address this function already validated
instead of letting httpx re-resolve, which is more invasive than this
app's webhook feature currently justifies. This is the same trade-off
almost every application-level SSRF guard makes.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}


def _is_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Deliberately NOT ip.is_private -- see the module docstring. A
    # private/RFC1918 address is exactly what a tenant's own internal
    # webhook target looks like on an air-gapped deployment.
    return ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


async def check_outbound_url(url: str) -> str | None:
    """None if `url` is safe to call; otherwise a human-readable reason
    it was rejected, suitable to show an admin or log."""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        return f"unsupported URL scheme {parts.scheme!r} -- only http/https are allowed"
    if not parts.hostname:
        return "URL has no host"

    try:
        # getaddrinfo is a blocking syscall; run it off the event loop
        # the same way any other blocking I/O in an async handler would
        # be, rather than stalling every other request being served
        # while DNS resolves.
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, None)
    except socket.gaierror as exc:
        return f"could not resolve host {parts.hostname!r}: {exc}"

    for info in infos:
        raw_ip = info[4][0]
        # IPv6 scope id (e.g. "fe80::1%eth0") isn't accepted by
        # ip_address -- strip it, same as it plays no part in whether
        # the address itself is link-local/loopback/etc.
        ip = ipaddress.ip_address(raw_ip.split("%", 1)[0])
        if _is_unsafe_ip(ip):
            return f"host {parts.hostname!r} resolves to {ip}, which this instance never calls out to"
    return None
