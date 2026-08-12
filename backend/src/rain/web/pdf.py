"""Server-side HTML -> PDF rendering for branded, downloadable exports
(ticket/asset/document detail views).

Deliberately reuses the same Jinja2 template engine as the rest of the app
rather than pulling in a headless browser: xhtml2pdf is pure Python (no
Chromium/wkhtmltopdf binary to install and patch inside the container) and
understands enough of CSS 2.1 for a simple printed-report layout. The
trade-off is a limited CSS subset (no flexbox/grid) -- the pdf/ templates
are written against that subset, separate from the app's normal screen
templates.
"""
from __future__ import annotations

import io
from pathlib import Path

from xhtml2pdf import pisa

from rain.core.config_store import config_store
from rain.settings import get_settings
from rain.web.templating import templates

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _link_callback(uri: str, rel: str) -> str:
    """Resolve the handful of local URL prefixes the PDF templates can
    reference (branding logo, static CSS/images) to real filesystem paths,
    since xhtml2pdf fetches assets itself rather than going through
    Starlette's routing."""
    if uri.startswith("/media/branding/"):
        path = Path(get_settings().uploads_dir) / "branding" / uri.removeprefix("/media/branding/")
    elif uri.startswith("/static/"):
        path = _STATIC_DIR / uri.removeprefix("/static/")
    else:
        return uri
    return str(path) if path.exists() else uri


def render_pdf(template_name: str, context: dict) -> bytes:
    """Render a Jinja2 template from web/templates/pdf/ to PDF bytes."""
    ctx = {"branding": config_store.as_dict(), **context}
    html = templates.get_template(template_name).render(ctx)
    buf = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buf, link_callback=_link_callback)
    if result.err:
        raise RuntimeError(f"PDF generation failed for template {template_name!r}")
    return buf.getvalue()
