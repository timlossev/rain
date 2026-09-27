"""Shared target-column list for every vulnerability-scanner import format
(.nessus, OpenVAS/GVM XML, and any future one) -- single source of truth so
rain.modules.tickets.nessus_parser and .openvas_parser can't drift apart on
these labels, the same reason each parser's own column list used to be
built from one tuple instead of repeated literal dict keys. These also
have to stay byte-identical to docs/compliance-templates/bundles/
vulnerability-scan-finding-fields.rain's own field labels for
rain.modules.tickets.router.import_preview's case-insensitive auto-
suggestion to keep wiring up a fully pre-filled mapping screen for either
format -- "Scanner check ID"/"Check name"/"Check family" are deliberately
vendor-neutral (a Nessus plugin ID and an OpenVAS/GVM NVT OID are the same
concept -- "which check produced this finding" -- under different scanner
vocabulary) so one template and one set of ticket fields covers both."""
from __future__ import annotations

SCAN_COLUMNS = [
    "Type",
    "Title",
    "Description",
    "Severity",
    "Dedup key (optional)",
    "Scanner check ID",
    "Check name",
    "Check family",
    "Scanned host",
    "Port",
    "Protocol",
    "CVSS base score",
    "Risk factor (scanner-assigned)",
    "Last seen in scan",
]
