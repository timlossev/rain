"""Helpers for documents whose file *is* plain text or Markdown -- both
the in-app inline editor and the PDF export read/render a document's
body the same way, via this module, so they can't drift apart on which
extensions are treated as editable/renderable or how Markdown is turned
into HTML."""
from __future__ import annotations

from pathlib import Path

import bleach
import markdown as _markdown

# What a rendered document body is actually allowed to contain -- render_markdown's
# output is injected as live HTML via innerHTML (the body-preview/preview-markdown
# routes) and via Jinja's |safe (the PDF export template), so unlike everywhere
# else user text reaches a page, autoescaping never gets a chance to run here;
# this allowlist is the only thing standing between a document body and
# arbitrary script execution in whoever's browser previews or exports it.
# Covers exactly what fenced_code/tables/sane_lists (render_markdown's own
# extensions) plus plain Markdown syntax can produce -- nothing exotic.
_ALLOWED_TAGS = [
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "b", "i", "code", "pre", "blockquote",
    "ul", "ol", "li",
    "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
]
_ALLOWED_ATTRS = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title"],
    "code": ["class"],  # fenced_code's language-xxx hint
}
# Blocks javascript:/data: hrefs and src values outright -- bleach strips the
# attribute entirely when its URL's scheme isn't one of these.
_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]

#: Anything that just wants a plain textarea (no Markdown rendering) --
#: XML/JSON included, since a config/manifest/API-response snapshot is
#: exactly the kind of thing this repository is for and "plain text" is
#: the right editing experience for it, not prose.
TEXT_EXTENSIONS = {".txt", ".text", ".log", ".xml", ".json"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
EDITABLE_EXTENSIONS = TEXT_EXTENSIONS | MARKDOWN_EXTENSIONS


def body_kind(filename: str) -> str | None:
    """'text' | 'markdown' | None (not an inline-editable/renderable type)."""
    ext = Path(filename or "").suffix.lower()
    if ext in MARKDOWN_EXTENSIONS:
        return "markdown"
    if ext in TEXT_EXTENSIONS:
        return "text"
    return None


def decode_body(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def render_markdown(text: str) -> str:
    # fenced_code/tables/sane_lists are the common-Markdown-superset bits
    # people actually expect (GitHub-flavored-ish); nothing exotic that
    # xhtml2pdf's limited CSS/HTML subset would choke on downstream.
    #
    # markdown.markdown() passes through any raw HTML already present in
    # the source verbatim -- that's Python-Markdown's documented behavior,
    # not a bug -- so the result is untrusted HTML, not safe-by-construction
    # markup, regardless of who authored the document. bleach.clean() is
    # what actually makes this safe to inject live (innerHTML/|safe) rather
    # than just escape-on-render the way every other user string in this
    # app is handled.
    rendered = _markdown.markdown(text, extensions=["fenced_code", "tables", "sane_lists"])
    return bleach.clean(
        rendered, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, protocols=_ALLOWED_PROTOCOLS, strip=True
    )
