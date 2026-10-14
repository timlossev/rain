"""Regenerates cmmc-level-3-controls.csv from the actual regulatory
text of Table 1 to 32 CFR 170.14(c)(4) -- the 24 additional CMMC Level
3 security requirements, selected by DoD from NIST SP 800-172 (Feb
2021). Fetched from eCFR's own versioner API (the authoritative,
machine-readable copy of the Code of Federal Regulations):
https://www.ecfr.gov/api/versioner/v1/full/<date>/title-32.xml?part=170

Unlike Level 1/Level 2 (which draw their 15/110 requirements from
documents with no further CMMC-specific selection), Level 3 is DoD's
own curated subset of the much larger NIST SP 800-172 catalog -- the
Federal Register final rule is the only place that selection and its
exact practice IDs (the "...e" suffix marks an *enhanced* requirement)
are both laid out together, which is why this parses the regulation
itself rather than NIST SP 800-172 directly.

One row per requirement (24 total). No separate short title exists in
the regulatory text (unlike Level 1's assessment guide, which names
each practice, e.g. "AUTHORIZED ACCESS CONTROL") -- Name is therefore
the practice ID plus its full requirement text, same convention
extract_soc2_controls.py already uses for a source with no distinct
title field of its own. Statement ID is always blank (no lettered
sub-parts). Column headers match security-control-register.rain's own
custom field labels exactly, so Assets > Import auto-suggests every
mapping. DoD-defined parameters (ODPs), italicized in the regulation's
own table, are folded back into plain text here -- an OSA's own value
for each is a per-tenant implementation detail (track it as the
asset's own Parameters/Remarks once you're actually implementing a
control, same as every other kit in this folder), not something a
starter register should hardcode.

Usage: download the XML with
`curl -A Mozilla/5.0 --compressed -o title-32-part-170.xml "https://www.ecfr.gov/api/versioner/v1/full/<today's date, YYYY-MM-DD>/title-32.xml?part=170"`
next to this script, then run `python3 extract_cmmc_level3.py`.
"""
from __future__ import annotations

import csv
import re

ROW_RE = re.compile(
    r'<TD[^>]*>\(\w+\)\s*([A-Z]{2}\.L3-[\w.]+)</TD>\s*<TD[^>]*>(.*?)</TD>',
    re.DOTALL,
)


def clean(text: str) -> str:
    # Strips the regulation's own <E T="03">...</E> emphasis tags
    # (DoD-defined-parameter italics) down to their plain text, plus
    # any stray HTML entity/whitespace noise.
    text = re.sub(r'<E[^>]*>', "", text)
    text = text.replace("</E>", "")
    text = text.replace("&#xA7;", "§")
    return re.sub(r"\s+", " ", text).strip()


def extract(xml_path: str) -> list[dict]:
    xml = open(xml_path, encoding="utf-8").read()
    # Table 1 sits between the first requirement row and the table's
    # own footnote -- bounding the search avoids matching anything
    # from a different table elsewhere in the same part.
    first_id = xml.find("AC.L3-3.1.2e")
    start = xml.rfind("<TR>", 0, first_id)
    end = xml.find("* Roman numerals in parentheses")
    rows = []
    for req_id, text in ROW_RE.findall(xml[start:end]):
        question = clean(text)
        rows.append({
            "Name": f"{req_id} {question}",
            "External ID": req_id,
            "Control ID": req_id,
            "Statement ID": "",
            "Control Question": question,
        })
    return rows


if __name__ == "__main__":
    rows = extract("title-32-part-170.xml")
    out_path = "cmmc-level-3-controls.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Name", "External ID", "Control ID", "Statement ID", "Control Question"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out_path}: {len(rows)} rows")
