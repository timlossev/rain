"""Regenerates iso-27001-2022-annex-a-controls.csv from the free ISO/IEC
27001:2022 Annex A control list published by Hightable:
https://hightable.io/wp-content/uploads/2023/09/ISO-27001-Controls-List-Free-Download.xlsx

One CSV row per Annex A control (93 total: 37 Organisational, 8 People,
14 Physical, 34 Technological) -- the sheet's own category rows (a bare
"5"/"6"/"7"/"8" in the Control Number column, with no Control Objective)
are skipped, not imported as their own asset. Column headers match
security-control-register.rain's own custom field labels exactly, same
convention extract_fedramp_baseline.py already established, so Assets >
Import auto-suggests every mapping -- the same generic "Security
Control" asset type covers both catalogs (there's no statement-level
breakdown in ISO 27001 the way NIST 800-53 has lettered sub-parts, so
Statement ID is always blank here).

Usage: download the xlsx from the URL above as iso27001.xlsx next to
this script, then run `python3 extract_iso27001_controls.py`.
"""
from __future__ import annotations

import csv
import re

import openpyxl

SHEET = "ISO 27001 Annex A Controls List"


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def extract(xlsx_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb[SHEET]
    rows = []
    for row in ws.iter_rows(min_row=1, values_only=True):
        _, control_number, title, objective = row[0], row[1], row[2], row[3]
        if control_number is None or not objective:
            continue  # category header row (e.g. bare "5"), or the sheet's own title/column-header rows
        control_id = str(control_number).strip()
        if not control_id[:1].isdigit():
            continue  # the sheet's own column-header row ("ISO 27001 Annex A Control Number") -- not a real control
        rows.append({
            "Name": f"{control_id} {clean(title)}",
            "External ID": control_id,
            "Control ID": control_id,
            "Statement ID": "",
            "Control Question": clean(objective),
        })
    return rows


if __name__ == "__main__":
    rows = extract("iso27001.xlsx")
    out_path = "iso-27001-2022-annex-a-controls.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Name", "External ID", "Control ID", "Statement ID", "Control Question"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out_path}: {len(rows)} rows")
