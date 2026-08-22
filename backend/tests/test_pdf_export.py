"""Regression test for a real xhtml2pdf/reportlab crash: exporting a
ticket whose content is long enough to need a page break used to raise
`TypeError: sequence item 0: expected str instance, list found` deep
inside reportlab's own error-reporting path -- triggered by pairing
`-pdf-word-wrap: CJK` (added to fix long-string overflow) with content
long enough to make reportlab split a paragraph across pages, which hits
a real bug in xhtml2pdf 0.2.17's own `Paragraph.getPlainText()`
(`"".join([frag.text] for frag in frags ...)` wraps each item in a list
before joining). No short-content render exercises that page-split path
at all, which is exactly why this shipped unnoticed -- this test uses
content sized specifically to force it. Fixed by dropping the CSS rule
(see rain.web.templates.pdf._base_pdf.html); this guards against
reintroducing it, or any other change that revives a page-split crash."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rain.web.pdf import _BLOCKED_URI, _link_callback
from rain.web.templating import templates


def test_link_callback_passes_through_inline_data_uris():
    # The raster (PNG/JPEG) branch of _logo_for_pdf hands the logo over
    # as a data: URI -- must reach xhtml2pdf unchanged, not get treated
    # as an untrusted external reference.
    uri = "data:image/png;base64,AAAA"
    assert _link_callback(uri, None) == uri


def test_link_callback_allows_a_real_svg_logo_under_the_branding_dir(tmp_path):
    branding_dir = tmp_path / "branding"
    branding_dir.mkdir()
    logo = branding_dir / "logo.svg"
    logo.write_text("<svg></svg>")

    class FakeSettings:
        uploads_dir = str(tmp_path)

    with patch("rain.web.pdf.get_settings", return_value=FakeSettings()):
        # _logo_for_pdf's SVG branch hands over an absolute filesystem
        # path directly (not a URL) -- must resolve to itself, not get
        # blocked as an unrecognized URI.
        assert _link_callback(str(logo), None) == str(logo.resolve())


def test_link_callback_blocks_paths_outside_the_branding_dir(tmp_path):
    branding_dir = tmp_path / "branding"
    branding_dir.mkdir()

    class FakeSettings:
        uploads_dir = str(tmp_path)

    with patch("rain.web.pdf.get_settings", return_value=FakeSettings()):
        assert _link_callback(str(tmp_path / "branding" / ".." / ".." / "etc" / "passwd"), None) == _BLOCKED_URI
        assert _link_callback("/etc/passwd", None) == _BLOCKED_URI


def test_link_callback_blocks_external_urls():
    # The actual SSRF fix: an <img src="http://..."> in a user-authored
    # document body must never reach xhtml2pdf's own fetcher.
    assert _link_callback("http://169.254.169.254/latest/meta-data/", None) == _BLOCKED_URI
    assert _link_callback("https://evil.example.com/x", None) == _BLOCKED_URI
    assert _link_callback("file:///etc/passwd", None) == _BLOCKED_URI


def _long_activity(n: int) -> list[dict]:
    return [
        {
            "kind": "comment",
            "at": dt.datetime(2026, 8, 23, 10, i % 59),
            "item": SimpleNamespace(
                author_user_id=None,
                body=f"Comment number {i}: " + "lots of text here to pad it out. " * 15,
            ),
        }
        for i in range(30)
    ]


def test_ticket_pdf_renders_with_enough_content_to_span_multiple_pages():
    from xhtml2pdf import pisa

    ticket = SimpleNamespace(
        ticket_number="INC-000001",
        title="Something broke",
        ticket_type="incident",
        severity="high",
        status="open",
        is_problematic=False,
        asset=None,
        assignee_user_id=None,
        reporter_user_id=None,
        reported_anonymously=True,
        source_rule=None,
        source_correlation_rule=None,
        source_event_id=None,
        source_ticket=None,
        start_date=None,
        end_date=None,
        approval=None,
        created_at=dt.datetime(2026, 8, 23, 10, 0),
        description="This is a long description. " * 40 + "\n\n" + "Second paragraph here. " * 40,
    )
    ctx = {
        "ticket": ticket,
        "document_links": [],
        "user_names": {},
        "asset_names": {},
        "status_labels": {"open": "Open"},
        "activity": _long_activity(30),
        "doc_kind": "Ticket",
        "generated_at": "2026-08-23 10:00",
        "branding": {"instance_name": "RAIN", "accent_color": "#6366f1", "logo_path": None},
    }
    html = templates.get_template("pdf/ticket.html").render(ctx)

    import io

    buf = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buf, link_callback=_link_callback)
    assert not result.err
    assert len(buf.getvalue()) > 0
