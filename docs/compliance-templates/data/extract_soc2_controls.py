"""Regenerates soc2-type2-controls.csv from the free SOC 2 Type II controls
list published by SecureSlate:
https://getsecureslate.com/downloads/secureslate-soc-2-controls-list.xlsx

One CSV row per control across every Trust Services Criteria the source
tracks (Security/Common Criteria, Availability, Confidentiality, Processing
Integrity, Privacy) -- pulled from the workbook's own "All Controls" sheet,
which is already the deduplicated union the other five category sheets each
show a filtered slice of (60 unique Control IDs either way). Column headers
match security-control-register.rain's own custom field labels exactly,
same convention extract_fedramp_baseline.py/extract_iso27001_controls.py
already established, so Assets > Import auto-suggests every mapping -- the
same generic "Security Control" asset type covers this catalog too. SOC 2
has no statement-level breakdown the way NIST 800-53 does, so Statement ID
is always blank here (same as the ISO 27001 kit). The source's other
columns (Owner, Frequency, Evidence Artifact/Source, Status, Last Reviewed,
Notes, ISO 27001 Ref, Control Type) describe your own implementation of a
control rather than the control itself, so they're not part of this starter
CSV -- fill them in as responsible_role/remarks/implementation_status on
the asset once you're actually implementing it.

Usage: download the xlsx from the URL above as soc2.xlsx next to this
script, then run `python3 extract_soc2_controls.py`.
"""
from __future__ import annotations

import csv
import re

import openpyxl

SHEET = "All Controls"


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def extract(xlsx_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb[SHEET]
    rows = []
    for control_id, _area, _category, activity, *_rest in ws.iter_rows(min_row=2, values_only=True):
        if not control_id or not activity:
            continue  # a blank trailing row, or a row missing its own control text
        control_id = str(control_id).strip()
        rows.append({
            "Name": f"{control_id} {clean(activity)}",
            "External ID": control_id,
            "Control ID": control_id,
            "Statement ID": "",
            "Control Question": clean(activity),
        })
    return rows


if __name__ == "__main__":
    rows = extract("soc2.xlsx")
    out_path = "soc2-type2-controls.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Name", "External ID", "Control ID", "Statement ID", "Control Question"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out_path}: {len(rows)} rows")
