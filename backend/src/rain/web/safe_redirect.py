"""Guards against an open redirect: a `next`/`return_to`-style query or
form value naming where to send the user back to is necessarily
user-controlled input, so it must never be handed to RedirectResponse
unchecked -- only a same-origin relative path is safe to honor."""
from __future__ import annotations

from starlette.requests import Request

from rain.settings import get_settings


def safe_relative_path(path: str | None, default: str = "/") -> str:
    if path and path.startswith("/") and not path.startswith("//"):
        return path
    return default


def public_origin(request: Request) -> str:
    """scheme://host for an absolute link sent OUTSIDE the current
    request/response cycle -- an emailed password-reset link, today.
    request.url.netloc reflects the incoming `Host` header, which
    nothing in front of the app validates unless Caddy's own
    RAIN_DOMAIN-matched site block happens to be what's deployed
    (WEB_FRONTEND=false, an ALB or other LB terminating TLS instead, is
    a documented deployment shape where it reaches this unchecked) --
    an attacker who controls Host on that request gets their own domain
    baked into a genuine reset email, one click from a real user's
    account. Settings.rain_domain is meant to be the one authoritative
    public domain (see its own docstring); this is the first thing that
    actually reads it for that purpose rather than just handing it to
    Caddy. Falls back to the live request's own host only when
    rain_domain is still the un-configured "localhost" default, where
    there's no real domain to prefer anyway."""
    settings = get_settings()
    host = settings.rain_domain if settings.rain_domain and settings.rain_domain != "localhost" else request.url.netloc
    return f"{request.url.scheme}://{host}"
