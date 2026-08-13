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


templates = Jinja2Templates(directory=str(TEMPLATES_DIR), context_processors=[_branding_context])
templates.env.globals["asset_version"] = ASSET_VERSION
