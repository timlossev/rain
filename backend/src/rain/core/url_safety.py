"""Guards outbound HTTP calls this app makes on a tenant's behalf --
webhooks (rain.modules.webhooks.service.call_webhook) and Slack
notifications (rain.modules.tickets.notifications.send_slack) -- against
SSRF: a tenant admin's URL (or a lower-privileged user's, for a webhook
already attached to something they can trigger) is otherwise sent
straight to httpx with no restriction on what host it resolves to,
letting it reach the platform's own internal network or a cloud
metadata endpoint (169.254.169.254) instead of whatever public service
it claims to be.

This validates the *scheme* and the *resolved IP* at call time (not just
when the URL is saved), which is what actually matters -- rejecting
"http://169.254.169.254/..." outright, and also catching a URL that
looked fine when an admin saved it but now resolves to a private/
loopback/link-local address. It is not a defense against a determined
DNS-rebinding attack (the resolution here and httpx's own resolution a
moment later are two separate lookups, so a nameserver that flips
answers between them could still slip a private IP past this check into
the real connection) -- closing that gap fully needs a custom transport
that connects to the address this function already validated instead of
letting httpx re-resolve, which is more invasive than this app's
webhook feature currently justifies. This is the same trade-off almost
every application-level SSRF guard makes.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}


def _is_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


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
        # the address itself is link-local/private/etc.
        ip = ipaddress.ip_address(raw_ip.split("%", 1)[0])
        if _is_unsafe_ip(ip):
            return f"host {parts.hostname!r} resolves to {ip}, which is not a publicly routable address"
    return None
