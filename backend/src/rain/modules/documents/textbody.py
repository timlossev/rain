"""Helpers for documents whose file *is* plain text or Markdown -- both
the in-app inline editor and the PDF export read/render a document's
body the same way, via this module, so they can't drift apart on which
extensions are treated as editable/renderable or how Markdown is turned
into HTML."""
from __future__ import annotations

from pathlib import Path

import markdown as _markdown

TEXT_EXTENSIONS = {".txt", ".text", ".log"}
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
    return _markdown.markdown(text, extensions=["fenced_code", "tables", "sane_lists"])
