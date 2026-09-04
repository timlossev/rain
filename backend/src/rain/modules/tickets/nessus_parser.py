"""Parses a `.nessus` file (Tenable's Nessus vulnerability scanner export
format -- plain, documented XML, not to be confused with the separate,
proprietary, typically-encrypted "Nessus DB" transfer format Tenable
doesn't publish a spec for and this module makes no attempt to read) into
the same flat `list[dict[str, Any]]` shape `rain.modules.tickets.
importer.parse_rows` already returns for CSV/JSON -- one dict per
`<ReportItem>` (a single finding on a single host/port), keyed exactly by
this importer's own target labels ("Type", "Title", "Description",
"Severity", "Dedup key (optional)") and by the field labels
`docs/compliance-templates/nessus-finding-fields.json` ships ("Nessus
plugin ID", "Scanned host", "Port", ...). That naming discipline is the
whole trick: `rain.modules.tickets.router.import_preview`'s existing
case-insensitive exact-label-match auto-suggestion wires every mapping
up on its own, with zero new matching code -- upload a `.nessus` file
and land on a fully pre-filled mapping screen, still reviewable and
editable there like any other import, rather than a silent bypass of it.

Severity-0 (Info) findings are dropped before they ever become a row --
they dominate a raw scan's finding count and aren't things anyone wants
filed as a ticket by default. Nessus's own 1-4 severity scale maps onto
RAIN's low/medium/high/critical one-for-one from there.

Parsed with defusedxml rather than the stdlib's xml.etree.ElementTree --
a `.nessus` file is an untrusted upload, and stdlib ElementTree has no
protection against entity-expansion/external-entity attacks baked in."""
from __future__ import annotations

import datetime as dt
from typing import Any

from defusedxml import ElementTree

_SEVERITY_BY_NESSUS_LEVEL = {"1": "low", "2": "medium", "3": "high", "4": "critical"}


def parse_nessus_rows(raw: bytes) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(raw)
    rows: list[dict[str, Any]] = []
    # The .nessus format carries a per-host scan-completion timestamp
    # (HostProperties' own HOST_END tag) in a handful of different date
    # formats across scan policy versions -- parsing that reliably isn't
    # worth the fragility for a "roughly when was this seen" field.
    # Import date is a simpler, always-correct-enough stand-in: it's
    # never later than the actual scan, and re-importing the same scan
    # file twice doesn't change it (same file, same day, in practice).
    import_date = dt.date.today().isoformat()

    for report_host in root.iter("ReportHost"):
        host = report_host.get("name", "")
        # HostProperties' own host-ip tag, when present, is more reliably
        # a real address than ReportHost's own `name` attribute (which
        # Nessus sometimes sets to a hostname/FQDN instead) -- preferred
        # for the dedup key and the "Scanned host" field, falling back to
        # the bare `name` attribute for a host with no HostProperties.
        host_ip = host
        for tag in report_host.iter("tag"):
            if tag.get("name") == "host-ip" and tag.text:
                host_ip = tag.text.strip()
                break

        for item in report_host.iter("ReportItem"):
            nessus_severity = item.get("severity", "0")
            if nessus_severity == "0":
                continue

            plugin_id = item.get("pluginID", "")
            plugin_name = item.get("pluginName", "")
            plugin_family = item.get("pluginFamily", "")
            port = item.get("port", "0")
            protocol_raw = (item.get("protocol", "") or "").lower()
            protocol = protocol_raw if protocol_raw in ("tcp", "udp", "icmp") else "other"

            def child_text(tag_name: str) -> str:
                el = item.find(tag_name)
                return el.text.strip() if el is not None and el.text else ""

            synopsis = child_text("synopsis")
            description = child_text("description")
            solution = child_text("solution")
            cves = [el.text.strip() for el in item.findall("cve") if el.text]

            long_description = "\n\n".join(
                part for part in (synopsis, description, solution, ("CVE(s): " + ", ".join(cves)) if cves else "") if part
            )

            host_label = f"{host_ip}:{port}" if port not in ("", "0") else host_ip
            rows.append(
                {
                    "Type": "vulnerability",
                    "Title": f"{plugin_name} ({host_label})" if plugin_name else f"Nessus plugin {plugin_id} ({host_label})",
                    "Description": long_description,
                    "Severity": _SEVERITY_BY_NESSUS_LEVEL.get(nessus_severity, "medium"),
                    "Dedup key (optional)": f"nessus:{host_ip.lower()}:{port}:{protocol}:{plugin_id}",
                    "Nessus plugin ID": plugin_id,
                    "Plugin name": plugin_name,
                    "Plugin family": plugin_family,
                    "Scanned host": host_ip,
                    "Port": port,
                    "Protocol": protocol,
                    "CVSS base score": child_text("cvss_base_score"),
                    "Risk factor (scanner-assigned)": child_text("risk_factor"),
                    "Last seen in scan": import_date,
                }
            )

    return rows


#: The fixed column set parse_nessus_rows always produces -- used by
#: rain.modules.tickets.importer.sniff_headers so the mapping screen has
#: something to show without re-parsing the file a second time just for
#: its header list (parse_rows() re-reads the stash separately at commit
#: time regardless, same two-pass shape CSV/JSON already have).
NESSUS_COLUMNS = [
    "Type",
    "Title",
    "Description",
    "Severity",
    "Dedup key (optional)",
    "Nessus plugin ID",
    "Plugin name",
    "Plugin family",
    "Scanned host",
    "Port",
    "Protocol",
    "CVSS base score",
    "Risk factor (scanner-assigned)",
    "Last seen in scan",
]
