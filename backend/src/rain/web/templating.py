from __future__ import annotations

import time
from pathlib import Path

from starlette.templating import Jinja2Templates

from rain.core.config_store import config_store

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Cache-busting query param for /static/* asset URLs. Fixed for the life of
# the process (i.e. changes on every deploy, since a new container = a new
# process), so browsers that cached CSS/JS from a previous version fetch the
# new file instead of silently keeping a stale copy -- without this, a page
# can render broken (e.g. a hover-only element showing unconditionally)
# until the user manually hard-refreshes.
ASSET_VERSION = str(int(time.time()))


def _branding_context(request):
    return {"branding": config_store.as_dict()}


def top_nav_label(nodes, path: str) -> str | None:
    """Label of the top-level nav category (Admin, Tickets, ...) whose href
    is the longest matching prefix of the current request path -- backs the
    "Menu > Category > Page" breadcrumb in base.html. Matches "/admin" and
    "/admin/users/3/edit" but not "/administration"."""
    best_label: str | None = None
    best_len = -1
    for node in nodes:
        href = node.href
        if not href:
            continue
        href_path = href.split("?", 1)[0].rstrip("/") or "/"
        matches = path == href_path or path.startswith(href_path + "/")
        if matches and len(href_path) > best_len:
            best_label = node.label
            best_len = len(href_path)
    return best_label


templates = Jinja2Templates(directory=str(TEMPLATES_DIR), context_processors=[_branding_context])
templates.env.globals["asset_version"] = ASSET_VERSION
templates.env.globals["top_nav_label"] = top_nav_label
