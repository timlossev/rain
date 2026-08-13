"""Guards against an open redirect: a `next`/`return_to`-style query or
form value naming where to send the user back to is necessarily
user-controlled input, so it must never be handed to RedirectResponse
unchecked -- only a same-origin relative path is safe to honor."""
from __future__ import annotations


def safe_relative_path(path: str | None, default: str = "/") -> str:
    if path and path.startswith("/") and not path.startswith("//"):
        return path
    return default
