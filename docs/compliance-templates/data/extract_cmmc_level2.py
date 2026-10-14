"""Regenerates cmmc-level-2-controls.csv from NIST's own official SP
800-171 Rev 2 security requirements export:
https://csrc.nist.gov/files/pubs/sp/800/171/r2/upd1/final/docs/sp800-171r2-security-reqs.csv

CMMC Level 2 is NIST SP 800-171 Rev 2's 110 security requirements
verbatim -- the CMMC Level 2 Assessment Guide just relabels each one
with a "DD.L2-" practice ID, DD being the two-letter CMMC domain
abbreviation for the requirement's own NIST family (see DOMAIN_ABBREV
below; confirmed against the CMMC Model Overview v2.0's domain list).
No separate "CMMC" source document carries its own control text to
parse -- the 110 practices and their wording ARE NIST SP 800-171 Rev
2's, which is why this script transforms NIST's own CSV rather than
scraping a CMMC-specific one.

One row per requirement (110 total, both Basic and Derived) -- same
shape as the other kits in this folder: Statement ID always blank (SP
800-171 Rev 2 has no lettered sub-statement breakdown the way NIST
800-53 does), Control Question is the requirement's own "Security
Requirement" text. Column headers match security-control-register.rain's
own custom field labels exactly, same convention
extract_fedramp_baseline.py/extract_iso27001_controls.py/
extract_soc2_controls.py already established, so Assets > Import
auto-suggests every mapping.

Usage: download the CSV from the URL above as
sp800-171r2-security-reqs.csv next to this script, then run
`python3 extract_cmmc_level2.py`.
"""
from __future__ import annotations

import csv
import re

DOMAIN_ABBREV: dict[str, str] = {
    "Access Control": "AC",
    "Audit and Accountability": "AU",
    "Awareness and Training": "AT",
    "Configuration Management": "CM",
    "Identification and Authentication": "IA",
    # NIST's own CSV spells this with a lowercase "r" ("Incident
    # response") -- normalized here since it's just this one family,
    # purely a typo in the source, not a different family.
    "Incident response": "IR",
    "Maintenance": "MA",
    "Media Protection": "MP",
    "Personnel Security": "PS",
    "Physical Protection": "PE",
    "Risk Assessment": "RA",
    "Security Assessment": "CA",
    "System and Communications Protection": "SC",
    "System and Information Integrity": "SI",
}


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def extract(csv_path: str) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            family = clean(row["Family"])
            abbrev = DOMAIN_ABBREV[family]
            nist_id = clean(row["Identifier"])  # e.g. "3.1.1"
            practice_id = f"{abbrev}.L2-{nist_id}"
            question = clean(row[" Security Requirement"])
            rows.append({
                "Name": f"{practice_id} {question}",
                "External ID": practice_id,
                "Control ID": practice_id,
                "Statement ID": "",
                "Control Question": question,
            })
        return rows


if __name__ == "__main__":
    rows = extract("sp800-171r2-security-reqs.csv")
    out_path = "cmmc-level-2-controls.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Name", "External ID", "Control ID", "Statement ID", "Control Question"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out_path}: {len(rows)} rows")
