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


#: Returned for any URI this callback refuses to resolve (see the `else`
#: branch below) -- schemeless, so xhtml2pdf's own FileNetworkManager
#: routes it to LocalFileURI (a plain local-disk open, no network
#: request) instead of NetworkFileUri, and it never resolves to a real
#: file, so the image just renders missing rather than partially working.
#: Returning "" instead would NOT block anything: pisaFileObject only
#: overrides its URI `if callback and (new := callback(...))`, so a
#: falsy return is silently ignored and it fetches the *original* URI
#: anyway -- confirmed against xhtml2pdf's own files.py.
_BLOCKED_URI = "/__blocked_by_pdf_link_callback__"


def _link_callback(uri: str, rel: str) -> str:
    """Resolve the handful of local URL prefixes the PDF templates can
    reference (branding logo, static CSS/images) to real filesystem paths,
    since xhtml2pdf fetches assets itself rather than going through
    Starlette's routing. Anything else is refused outright, not passed
    through -- a document body is user-authored Markdown (rain.modules.
    documents.textbody.render_markdown), and its rendered HTML lands in
    this same PDF template with |safe, so an <img src="http://..."> in
    someone's document would otherwise make xhtml2pdf fetch an
    attacker-chosen URL from the server itself (SSRF) every time that
    document is exported to PDF."""
    if uri.startswith("data:"):
        # Inline data -- FileNetworkManager already has safe native
        # support for this (no network or filesystem access involved at
        # all), same as it does for /media/branding and /static below.
        # This is how _logo_for_pdf hands over a raster (PNG/JPEG) logo
        # once it's been flattened onto white -- see its own docstring.
        return uri
    if uri.startswith("/media/branding/"):
        path = Path(get_settings().uploads_dir) / "branding" / uri.removeprefix("/media/branding/")
    elif uri.startswith("/static/"):
        path = _STATIC_DIR / uri.removeprefix("/static/")
    else:
        # _logo_for_pdf's own SVG branch hands over an absolute
        # filesystem path directly (not a URL) for an SVG logo, since
        # svg2rlg reads straight off disk -- already resolved server-
        # side from a real file under uploads_dir/branding, never from
        # unsanitized input at this point, so safe to pass through as
        # long as it's actually confined to that one directory.
        branding_dir = (Path(get_settings().uploads_dir) / "branding").resolve()
        candidate = Path(uri)
        if candidate.is_absolute():
            try:
                resolved = candidate.resolve()
            except OSError:
                return _BLOCKED_URI
            if resolved.is_relative_to(branding_dir):
                return str(resolved) if resolved.exists() else _BLOCKED_URI
        return _BLOCKED_URI
    return str(path) if path.exists() else _BLOCKED_URI


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
