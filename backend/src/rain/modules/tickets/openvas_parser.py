"""Parses an OpenVAS/GVM (Greenbone Vulnerability Management) scan report
XML export into the same flat `list[dict[str, Any]]` shape `rain.modules.
tickets.importer.parse_rows` already returns for CSV/JSON/.nessus -- one
dict per `<result>` (a single finding on a single host/port), keyed
exactly by the same vendor-neutral target labels rain.modules.tickets.
nessus_parser uses (see rain.modules.tickets.vuln_scan_columns for why),
so `docs/compliance-templates/bundles/vulnerability-scan-finding-fields.rain`
and rain.modules.tickets.router.import_preview's auto-suggestion cover
this format for free, no separate template or matching code needed.

Exported via the GSA web UI ("Report > Download > XML") or `gvm-cli`/
`omp -X`, all producing the same `<report><report>...<results>` shape
(the outer `<report>` is envelope metadata -- id, format_id, task
reference; the actual findings sit in the inner one). This walks every
`<result>` anywhere in the document via `.iter()` rather than assuming
that exact nesting, the same defensive choice rain.modules.tickets.
nessus_parser makes for `<ReportHost>`/`<ReportItem>` -- GVM's own
nesting has shifted across major versions.

"Log"/"Debug"/"False Positive" threat levels are dropped before they
ever become a row -- OpenVAS's own equivalent of Nessus's Info (severity
0) findings, the ones that dominate a raw scan's result count and aren't
things anyone wants filed as a ticket by default. Only Low/Medium/High/
Critical produce rows.

Parsed with defusedxml rather than the stdlib's xml.etree.ElementTree --
a scan export is an untrusted upload, same reasoning as the .nessus
parser."""
from __future__ import annotations

import datetime as dt
from typing import Any

from defusedxml import ElementTree

from rain.modules.tickets.vuln_scan_columns import SCAN_COLUMNS

#: Kept as a re-export for the same reason nessus_parser.py re-exports
#: NESSUS_COLUMNS -- callers (rain.modules.tickets.importer) import a
#: format-specific name even though both lists are really the one
#: shared SCAN_COLUMNS.
OPENVAS_COLUMNS = SCAN_COLUMNS

_ROW_THREATS = {"low", "medium", "high", "critical"}

#: GVM's own placeholder text for "this NVT has no CVE/BID/reference" --
#: not a real identifier, so it's filtered out rather than landing in a
#: ticket's description as if it were one.
_NO_VALUE_PLACEHOLDERS = {"nocve", "nobid", "noxref"}


def _row(*values: Any) -> dict[str, Any]:
    return dict(zip(OPENVAS_COLUMNS, values))


def _text(el, tag: str) -> str:
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def _parse_tags(raw: str) -> dict[str, str]:
    """GVM's <nvt><tags> is one string, pipe-separated key=value pairs
    (e.g. "summary=...|insight=...|solution=...|solution_type=Mitigation"),
    not its own nested XML -- split on the first "=" per chunk only, since
    a value (a URL, a base64 blob) can itself contain "="."""
    tags: dict[str, str] = {}
    for chunk in raw.split("|"):
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        tags[key.strip()] = value.strip()
    return tags


def _split_port(raw: str) -> tuple[str, str]:
    """GVM's own <port> is one string, "443/tcp", "general/tcp" (a host-
    level check with no specific port), or occasionally just a bare
    number -- split into RAIN's own separate Port/Protocol columns
    (matching the .nessus importer's own two-column shape) rather than
    passing the combined string through as-is."""
    if not raw or raw == "general/tcp":
        return "0", "tcp"
    port, _, protocol = raw.partition("/")
    protocol = protocol.lower() if protocol.lower() in ("tcp", "udp", "icmp") else "other"
    return (port if port.isdigit() else "0"), protocol


def parse_openvas_rows(raw: bytes) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(raw)
    rows: list[dict[str, Any]] = []
    # GVM's own per-result creation_time is present but its format has
    # shifted across versions -- import date is a simpler, always-
    # correct-enough stand-in, same choice and same reasoning as
    # rain.modules.tickets.nessus_parser's own import_date.
    import_date = dt.date.today().isoformat()

    for result in root.iter("result"):
        threat = _text(result, "threat").lower()
        if threat not in _ROW_THREATS:
            continue  # Log/Debug/False Positive -- OpenVAS's own Info-equivalent

        host_el = result.find("host")
        host = (host_el.text or "").strip() if host_el is not None else ""
        port_raw = _text(result, "port")
        port, protocol = _split_port(port_raw)

        nvt = result.find("nvt")
        oid = nvt.get("oid", "") if nvt is not None else ""
        nvt_name = _text(nvt, "name") if nvt is not None else ""
        nvt_family = _text(nvt, "family") if nvt is not None else ""
        cve_raw = _text(nvt, "cve") if nvt is not None else ""
        cves = [c.strip() for c in cve_raw.split(",") if c.strip() and c.strip().lower() not in _NO_VALUE_PLACEHOLDERS]

        tags = _parse_tags(_text(nvt, "tags")) if nvt is not None else {}
        # <description> is GVM's own free-text finding summary when
        # present; older/minimal exports sometimes omit it, so the
        # <tags> "summary" falls back to filling that same role.
        summary = _text(result, "description") or tags.get("summary", "")
        solution = tags.get("solution", "")
        long_description = "\n\n".join(
            part for part in (summary, solution, ("CVE(s): " + ", ".join(cves)) if cves else "") if part
        )

        # Effective (possibly override-adjusted) score/severity live on
        # the <result> itself, not the <nvt> -- preferred over the nvt's
        # own <cvss_base> the same way rain.modules.tickets.nessus_parser
        # prefers a ReportItem's own severity over the plugin's baseline.
        cvss = _text(result, "severity") or _text(nvt, "cvss_base") if nvt is not None else _text(result, "severity")

        host_label = f"{host}:{port}" if port != "0" else host
        rows.append(
            _row(
                "vulnerability",
                f"{nvt_name} ({host_label})" if nvt_name else f"OpenVAS check {oid} ({host_label})",
                long_description,
                threat,
                f"openvas:{host.lower()}:{port}:{protocol}:{oid}",
                oid,
                nvt_name,
                nvt_family,
                host,
                port,
                protocol,
                cvss,
                threat.capitalize(),
                import_date,
            )
        )

    return rows
