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

import base64
import io
from pathlib import Path

from PIL import Image
from svglib.svglib import svg2rlg
from xhtml2pdf import pisa

from rain.core.config_store import config_store
from rain.settings import get_settings
from rain.web.templating import templates

_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Render height for the branding logo in the PDF header, in points/px.
_LOGO_HEIGHT = 30


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


def _logo_for_pdf(branding: dict) -> dict:
    """Prepares the branding logo for the PDF header.

    Two problems with handing xhtml2pdf the raw upload directly (the old
    behaviour): (1) reportlab's PNG decoder doesn't composite alpha
    transparency onto the page background for palette-indexed PNGs (a common
    output of logo/design tools) -- it renders the raw, non-transparent
    placeholder color baked into the palette instead, which shows up as a
    solid color (often green) filling the "transparent" area. Flattening
    onto white here in Python sidesteps that renderer limitation entirely.
    (2) the old template forced a fixed 30x30 box regardless of the source
    image's aspect ratio, squashing any non-square logo. Computing a
    proportional width here (both for raster images via Pillow and for SVG
    via svglib, which xhtml2pdf already depends on for SVG support) fixes
    that too.
    """
    logo_path = branding.get("logo_path")
    if not logo_path or not logo_path.startswith("/media/branding/"):
        return {}
    path = Path(get_settings().uploads_dir) / "branding" / logo_path.removeprefix("/media/branding/")
    if not path.exists():
        return {}
    if path.suffix.lower() == ".svg":
        try:
            drawing = svg2rlg(str(path))
            if not drawing or not drawing.width or not drawing.height:
                return {}
            width = max(1, round(drawing.width * (_LOGO_HEIGHT / drawing.height)))
            return {"pdf_logo_src": str(path), "pdf_logo_width": width, "pdf_logo_height": _LOGO_HEIGHT}
        except Exception:
            return {}
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            flattened = Image.new("RGB", im.size, "white")
            flattened.paste(im, mask=im.split()[3])
            width = max(1, round(flattened.width * (_LOGO_HEIGHT / flattened.height)))
            buf = io.BytesIO()
            flattened.save(buf, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        return {"pdf_logo_src": data_uri, "pdf_logo_width": width, "pdf_logo_height": _LOGO_HEIGHT}
    except Exception:
        return {}


def render_pdf(template_name: str, context: dict) -> bytes:
    """Render a Jinja2 template from web/templates/pdf/ to PDF bytes."""
    branding = config_store.as_dict()
    ctx = {"branding": branding, **_logo_for_pdf(branding), **context}
    html = templates.get_template(template_name).render(ctx)
    buf = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buf, link_callback=_link_callback)
    if result.err:
        raise RuntimeError(f"PDF generation failed for template {template_name!r}")
    return buf.getvalue()
