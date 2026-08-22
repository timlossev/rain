"""Regression tests for the security-review fixes: CSV/XLSX formula
injection, the asset-import stash token's path-traversal guard, Markdown
body sanitization, and the outbound-URL SSRF guard's pure (no-DNS)
rejection paths. Split out from test_pure_functions.py since these are
specifically locking in a vulnerability class each, not general
behavior."""
from __future__ import annotations

import pytest

from rain.core.url_safety import check_outbound_url
from rain.core.xlsx_export import neutralize_formula
from rain.modules.documents.textbody import render_markdown
from rain.web.uploads import import_stash_path


def test_neutralize_formula_prefixes_formula_trigger_chars():
    for value in ("=cmd|'/c calc'!A0", "+1+1", "-1-1", "@SUM(A1:A2)", "\ttab", "\rcr"):
        assert neutralize_formula(value) == "'" + value


def test_neutralize_formula_leaves_ordinary_values_alone():
    assert neutralize_formula("a normal title") == "a normal title"
    assert neutralize_formula("web-01") == "web-01"
    assert neutralize_formula(None) is None
    assert neutralize_formula(42) == 42


def test_import_stash_path_accepts_a_real_token(tmp_path, monkeypatch):
    from rain.settings import get_settings

    monkeypatch.setattr(get_settings(), "uploads_dir", str(tmp_path))
    path = import_stash_path("3f08f66b24e67bf025074a6c1956f90c")
    assert path.parent == tmp_path / "import-stash"
    assert path.name == "3f08f66b24e67bf025074a6c1956f90c.bin"


@pytest.mark.parametrize(
    "token",
    ["/etc/passwd", "../../../etc/passwd", "abc", "", "3f08f66b24e67bf025074a6c1956f90c/../x"],
)
def test_import_stash_path_rejects_anything_not_shaped_like_a_real_token(token):
    with pytest.raises(ValueError):
        import_stash_path(token)


def test_render_markdown_strips_event_handler_attributes():
    rendered = render_markdown("<img src=x onerror=alert(1)>")
    assert "onerror" not in rendered
    assert "<img" in rendered  # the tag itself is allowed, just not the handler


def test_render_markdown_strips_script_tags():
    rendered = render_markdown("<script>alert(1)</script>")
    assert "<script" not in rendered


def test_render_markdown_strips_javascript_href():
    rendered = render_markdown("[click me](javascript:alert(1))")
    assert "javascript:" not in rendered


def test_render_markdown_preserves_legitimate_content():
    rendered = render_markdown("![a photo](https://example.com/logo.png)")
    assert 'src="https://example.com/logo.png"' in rendered
    rendered = render_markdown("[a link](https://example.com)")
    assert 'href="https://example.com"' in rendered


async def test_check_outbound_url_rejects_non_http_schemes():
    assert await check_outbound_url("file:///etc/passwd") is not None
    assert await check_outbound_url("ftp://example.com") is not None


async def test_check_outbound_url_rejects_missing_host():
    assert await check_outbound_url("http://") is not None
