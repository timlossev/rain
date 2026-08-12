from __future__ import annotations

from pathlib import Path

from starlette.templating import Jinja2Templates

from rain.core.config_store import config_store

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _branding_context(request):
    return {"branding": config_store.as_dict()}


templates = Jinja2Templates(directory=str(TEMPLATES_DIR), context_processors=[_branding_context])
