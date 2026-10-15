"""Parses an Amazon Inspector findings report (the JSON export -- see
"Why JSON, not CSV" below) into the same flat `list[dict[str, Any]]`
shape `rain.modules.tickets.importer.parse_rows` already returns for
CSV/JSON/.nessus/OpenVAS -- one dict per finding, keyed exactly by the
same vendor-neutral target labels rain.modules.tickets.vuln_scan_columns
defines, so docs/compliance-templates/bundles/vulnerability-scan-
finding-fields.rain and rain.modules.tickets.router.import_preview's
auto-suggestion cover AWS Inspector for free, same as Nessus/OpenVAS
already get -- no separate template, no separate FedRAMP CR26 VER
mapping to build, since it rides the one that already exists.

Field names below are exactly the Inspector v2 "Finding" API shape --
https://docs.aws.amazon.com/inspector/v2/APIReference/API_Finding.html
and its nested PackageVulnerabilityDetails/Resource/CvssScore/
VulnerablePackage/Remediation objects -- verified against that
reference directly, not guessed from a CSV column header (see "Why
JSON, not CSV" below). Export this report format from the Inspector
console (Findings > All findings > Export findings > JSON) or via the
CreateFindingsReport API (reportFormat=JSON).

Why JSON, not CSV: Inspector's own docs describe the CSV export as "a
subset of ~45 fields" with no published, stable list of exact header
names, while the JSON export is documented to carry "all the fields
for each finding, matching the Finding data type" -- i.e. exactly the
API shape this module reads. Rather than guess at undocumented CSV
headers and risk silently mis-mapping a column (the opposite of what
this import path is for), this only reads the fully-specified JSON
export. If your workflow only ever produces CSV, convert it to JSON
with `aws inspector2 list-findings` or `create-findings-report` instead
of the console's CSV button.

File shape: AWS doesn't publish whether the exported JSON file is a
plain array of Finding objects or one Finding per line (JSON Lines) --
both this module and the API docs are silent on it, and there's no way
to confirm the real envelope without a live instance's own export.
Handled defensively: try parsing the whole file as one JSON document
first (an array, or a single finding/object wrapping an array under
a "findings"/"Findings" key); if that raises (consistent with JSON
Lines, where a second top-level value makes the whole blob invalid
JSON), fall back to parsing it one line at a time. If your export
turns out to need a third shape, that's a real gap worth reporting,
not a guess this module already covers.

INFORMATIONAL findings are dropped before they ever become a row, the
same "Info-equivalent findings are noise, not tickets" convention
nessus_parser/openvas_parser both already use. UNTRIAGED (the vendor
hasn't assigned a severity yet) maps to "medium" rather than being
dropped -- it's a real, unclassified finding, not a known-benign one,
so silently excluding it would hide genuine findings rather than just
noise.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from rain.modules.tickets.vuln_scan_columns import SCAN_COLUMNS

#: Kept as a re-export for the same reason nessus_parser.py/
#: openvas_parser.py each re-export their own format-specific name.
INSPECTOR_COLUMNS = SCAN_COLUMNS

_SEVERITY_BY_INSPECTOR_LEVEL = {
    "LOW": "low",
    "MEDIUM": "medium",
    "HIGH": "high",
    "CRITICAL": "critical",
    "UNTRIAGED": "medium",
}


def _row(*values: Any) -> dict[str, Any]:
    return dict(zip(INSPECTOR_COLUMNS, values))


def _parse_findings(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Likely JSON Lines -- one finding object per line -- rather
        # than one JSON document for the whole file. Blank lines
        # (a trailing newline, say) are skipped; anything else that
        # still doesn't parse is a real malformed-file error, not
        # swallowed here.
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("findings", "Findings"):
            if isinstance(data.get(key), list):
                return data[key]
        if "findingArn" in data:
            return [data]
    raise ValueError("Unrecognized Amazon Inspector findings report shape -- expected a JSON array of findings.")


def _best_cvss_score(cvss_list: list[dict[str, Any]]) -> str:
    if not cvss_list:
        return ""
    # Prefer NVD's own score when more than one source reported one
    # (the same "most authoritative source wins" choice nessus_parser's
    # cvss_base_score makes implicitly by only ever reading one tag) --
    # falls back to whichever is first otherwise.
    for entry in cvss_list:
        if str(entry.get("source", "")).upper() == "NVD":
            return str(entry.get("baseScore", ""))
    return str(cvss_list[0].get("baseScore", ""))


def parse_inspector_rows(raw: bytes) -> list[dict[str, Any]]:
    findings = _parse_findings(raw)
    rows: list[dict[str, Any]] = []
    import_date = dt.date.today().isoformat()

    for finding in findings:
        inspector_severity = str(finding.get("severity", "")).upper()
        if inspector_severity == "INFORMATIONAL":
            continue

        resources = finding.get("resources") or [{}]
        resource = resources[0]
        resource_id = str(resource.get("id", "") or "")
        resource_type = str(resource.get("type", "") or "")

        pkg_details = finding.get("packageVulnerabilityDetails") or {}
        vulnerability_id = str(pkg_details.get("vulnerabilityId", "") or "")
        cvss_score = _best_cvss_score(pkg_details.get("cvss") or [])

        vulnerable_packages = pkg_details.get("vulnerablePackages") or []
        package_lines = [
            f"{p.get('name', '')} {p.get('version', '')}"
            + (f" (fixed in {p['fixedInVersion']})" if p.get("fixedInVersion") else "")
            for p in vulnerable_packages
        ]

        recommendation = ((finding.get("remediation") or {}).get("recommendation") or {}).get("text", "")

        description_parts = [
            finding.get("description", ""),
            ("Affected package(s): " + "; ".join(package_lines)) if package_lines else "",
            ("Remediation: " + recommendation) if recommendation else "",
            ("CVE(s): " + vulnerability_id) if vulnerability_id else "",
        ]
        description = "\n\n".join(part for part in description_parts if part)

        title = finding.get("title") or vulnerability_id or "Amazon Inspector finding"
        title_with_resource = f"{title} ({resource_id})" if resource_id else title

        severity = _SEVERITY_BY_INSPECTOR_LEVEL.get(inspector_severity, "medium")
        check_id = vulnerability_id or finding.get("type", "")
        last_observed = finding.get("lastObservedAt") or import_date

        rows.append(
            _row(
                "vulnerability",
                title_with_resource,
                description,
                severity,
                f"inspector:{finding.get('findingArn', '')}",
                check_id,
                title,
                resource_type or finding.get("type", ""),
                resource_id,
                "",
                "",
                cvss_score,
                inspector_severity.capitalize(),
                str(last_observed)[:10],
            )
        )

    return rows
