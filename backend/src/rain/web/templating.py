from __future__ import annotations

import logging
import time
from pathlib import Path

from markupsafe import Markup, escape
from starlette.templating import Jinja2Templates

from rain.core.config_store import config_store

logger = logging.getLogger("rain.templating")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Cache-busting query param for /static/* asset URLs. Fixed for the life of
# the process (i.e. changes on every deploy, since a new container = a new
# process), so browsers that cached CSS/JS from a previous version fetch the
# new file instead of silently keeping a stale copy -- without this, a page
# can render broken (e.g. a hover-only element showing unconditionally)
# until the user manually hard-refreshes.
ASSET_VERSION = str(int(time.time()))


def _tenant_schema_build() -> str:
    """The tenant migration chain's head revision (e.g. "0021"), shown as
    "Build 0021" in the user menu on every page -- a glance at which schema
    a given deployment is running without reaching for `alembic history` or
    a DB shell. Derived from the migrations/ directory itself (not
    hand-maintained) so it's automatically correct every time a new
    revision file is added -- nothing to remember to bump. Read once at
    import time, not per-request: rain.main's lifespan runs every tenant
    schema to this exact head before the app starts serving, so what's
    on disk here *is* what's applied for the life of this process."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        from rain.db.migrate import ALEMBIC_INI, MIGRATIONS_DIR

        cfg = Config(str(ALEMBIC_INI), ini_section="tenant")
        cfg.set_main_option("script_location", str(MIGRATIONS_DIR / "tenant"))
        return ScriptDirectory.from_config(cfg).get_current_head() or "?"
    except Exception:
        logger.exception("could not determine tenant schema build number")
        return "?"


DB_BUILD = _tenant_schema_build()


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


def nl2br(value: str | None) -> Markup:
    """Explicit line breaks for free text (a ticket description, a
    comment body, a plain-text document body) that's meant to keep its
    original line breaks -- needed specifically for the PDF export
    templates (rain.web.pdf), which reuse this same Jinja2 environment.
    A normal browser honors a literal "\\n" inside a block element (or
    inside a <pre> with white-space: pre-wrap, as the web preview/inline
    editor already rely on), but xhtml2pdf's reportlab-based text flow
    doesn't -- confirmed live: a <pre> with three literal newlines and
    that same CSS still extracted as one run-on line with no breaks at
    all. Each line is escaped individually (not the whole value first)
    so this is still autoescape-safe to use directly in a template."""
    if not value:
        return Markup("")
    return Markup("<br>\n").join(escape(line) for line in str(value).split("\n"))


templates = Jinja2Templates(directory=str(TEMPLATES_DIR), context_processors=[_branding_context])
templates.env.globals["asset_version"] = ASSET_VERSION
templates.env.globals["top_nav_label"] = top_nav_label
templates.env.globals["db_build"] = DB_BUILD
templates.env.filters["nl2br"] = nl2br
