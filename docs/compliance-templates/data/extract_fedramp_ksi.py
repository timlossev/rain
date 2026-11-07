"""Regenerates fedramp-20x-key-security-indicators.csv from FedRAMP's
own machine-readable consolidated rules:
https://raw.githubusercontent.com/FedRAMP/rules/main/fedramp-consolidated-rules.json

Unlike the CCM/MTCS/C5 kits in this same directory, this one is a
U.S. government work with no license restriction on redistributing an
adapted copy, so the output ships as a ready CSV the same way the
NIST/ISO/SOC2/CMMC kits do -- this script exists only to regenerate it
later (a future Key Security Indicator revision), not as a required
setup step.

The file's top-level "KSI" key holds one object per family (CED, CMT,
CNA, IAM, INR, MLA, PIY, RPL, SCR, SVC as of the 2026.11.02.01
release), each with an "indicators" map keyed by the indicator's own
ID (e.g. "KSI-CNA-DFP"). An indicator's "statement" is the baseline
requirement text; some instead (or also) carry "varies_by_class" with
per-class ("A"/"B"/"C"/"D") statement overrides -- this takes the
plain "statement" when present, falling back to the first class
variant's own statement otherwise, so every row still gets a Control
Question even for the handful of indicators that only define one by
class. "controls" is the indicator's own list of related NIST 800-53
control IDs, joined here as a plain comma-separated list (same flat-
list convention software-component.rain's own "Known vulnerabilities"
field already uses) -- cross-reference, not a lettered sub-statement
breakdown, so Statement ID stays blank like every other kit here.

Column headers beyond the usual five (Name, External ID, Control ID,
Statement ID, Control Question) match fedramp-ksi-starter-kit.rain's
own custom field labels exactly, so Assets > Import auto-suggests
every mapping the same way it does for every other kit.

Usage: download the JSON from the URL above as
fedramp-consolidated-rules.json next to this script, then run
`python3 extract_fedramp_ksi.py`.
"""
from __future__ import annotations

import csv
import json
import re

IN_PATH = "fedramp-consolidated-rules.json"
OUT_PATH = "fedramp-20x-key-security-indicators.csv"


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def statement_of(indicator: dict) -> str:
    if indicator.get("statement"):
        return clean(indicator["statement"])
    variants = indicator.get("varies_by_class") or {}
    for variant in variants.values():
        if variant.get("statement"):
            return clean(variant["statement"])
    return ""


def extract(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for family in data["KSI"].values():
        family_label = f"{family['name']} ({family['short_name']})"
        for ksi_id, indicator in family["indicators"].items():
            rows.append({
                "Name": f"{ksi_id} {clean(indicator.get('name'))}",
                "External ID": ksi_id,
                "Control ID": ksi_id,
                "Statement ID": "",
                "Family": family_label,
                "Related Controls": ", ".join(indicator.get("controls") or []),
                "Control Question": statement_of(indicator),
            })
    return rows


if __name__ == "__main__":
    rows = extract(IN_PATH)
    fieldnames = ["Name", "External ID", "Control ID", "Statement ID", "Family", "Related Controls", "Control Question"]
    with open(OUT_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT_PATH}: {len(rows)} rows")
