"""Regression tests for the security-review fixes: CSV/XLSX formula
injection, the asset-import stash token's path-traversal guard, Markdown
body sanitization, and the outbound-URL SSRF guard's pure (no-DNS)
rejection paths. Split out from test_pure_functions.py since these are
specifically locking in a vulnerability class each, not general
behavior."""
from __future__ import annotations

import ipaddress

import pytest

from rain.core.url_safety import _is_unsafe_ip, check_outbound_url
from rain.core.xlsx_export import neutralize_formula
from rain.modules.documents.textbody import render_markdown
from rain.modules.search.service import _headline_to_html
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


@pytest.mark.parametrize("addr", ["10.0.0.5", "192.168.1.1", "172.16.0.1", "8.8.8.8", "2001:4860:4860::8888"])
def test_is_unsafe_ip_allows_private_and_public_addresses(addr):
    # RAIN is built to run air-gapped -- a tenant's webhook reaching its
    # own internal network (an on-prem monitoring tool, an internal API)
    # on a private/RFC1918 address is the normal, intended case here,
    # not an attack. Regression test for exactly that: a real report of
    # a legitimate webhook to a private IP being rejected.
    assert _is_unsafe_ip(ipaddress.ip_address(addr)) is False


@pytest.mark.parametrize(
    "addr",
    ["127.0.0.1", "::1", "169.254.169.254", "169.254.170.2", "224.0.0.1", "0.0.0.0"],
)
def test_is_unsafe_ip_still_blocks_loopback_and_link_local(addr):
    # Loopback (would reach this app's own container instead of the
    # webhook's claimed target) and link-local (169.254.0.0/16 is what
    # actually covers a cloud metadata endpoint -- 169.254.169.254 on
    # AWS/GCP, 169.254.170.2 on AWS ECS) are never a legitimate webhook
    # target in any deployment, air-gapped or not -- unlike a private
    # RFC1918 address, these stay blocked.
    assert _is_unsafe_ip(ipaddress.ip_address(addr)) is True


def test_headline_to_html_escapes_html_in_the_matched_source_text():
    """Regression for search.service's own stated invariant: a ts_headline
    result is escaped *before* the \\x01/\\x02 sentinels are swapped for
    <mark>/</mark>, so a ticket/document title containing real HTML (never
    sanitized on the way in) can never smuggle a tag through a search
    result's highlighted snippet."""
    raw = "\x01<script>alert(1)</script>\x02 still here"
    rendered = str(_headline_to_html(raw))
    assert rendered == "<mark>&lt;script&gt;alert(1)&lt;/script&gt;</mark> still here"
    assert "<script>" not in rendered


def test_headline_to_html_none_and_empty_input():
    assert _headline_to_html(None) is None
    assert _headline_to_html("") is None


def test_headline_to_html_plain_text_with_no_match_markers():
    assert str(_headline_to_html("no highlight here")) == "no highlight here"
