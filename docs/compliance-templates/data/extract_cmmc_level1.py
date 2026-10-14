"""Regenerates cmmc-level-1-controls.csv from the CMMC Self-Assessment
Guide -- Level 1, Version 2.0 (December 2021), co-authored by Carnegie
Mellon SEI and Johns Hopkins APL under DoD contract -- the source
document for the model's own domain-labeled practice IDs and short
titles (NIST SP 800-171A's own assessment-objective text doesn't carry
either). Official copy:
https://dodcio.defense.gov/Portals/0/Documents/CMMC/AssessmentGuideL1.pdf
(that host blocks non-browser user agents; a plain `curl` needs a
browser-like User-Agent, or use a mirror of the same Version 2.0 PDF).

CMMC Level 1 is exactly the 17 practices covering FAR 52.204-21(b)'s 15
basic safeguarding requirements for Federal Contract Information (one
requirement maps to more than one practice in a couple of places,
hence 17 practices from 15 requirements) -- a small, fixed set that
hasn't changed revisions the way Level 2/3 have, which is why this
parses a single guide PDF rather than a versioned machine-readable feed
the way extract_cmmc_level2.py/extract_cmmc_level3.py do.

One row per practice (17 total). Name is the practice ID plus the
guide's own short title (e.g. "AC.L1-3.1.1 Authorized Access Control"),
same convention the NIST 800-53/ISO 27001 kits in this folder use for a
source that does carry a distinct title. Statement ID is always blank
(no lettered sub-parts at Level 1). Control Question is the guide's own
practice statement, reproduced verbatim. Column headers match
security-control-register.rain's own custom field labels exactly, so
Assets > Import auto-suggests every mapping.

Usage: save the guide as cmmc-level-1-guide.pdf next to this script
(pypdf must extract real text, not an image scan -- the dodcio.
defense.gov original and the CMU/JHU-authored Version 2.0 mirrors both
do), then run `python3 extract_cmmc_level1.py`.
"""
from __future__ import annotations

import csv
import re

from pypdf import PdfReader

# Matches e.g. "AC.L1-3.1.1 – AUTHORIZED ACCESS CONTROL\n<statement
# text>\nASSESSMENT OBJECTIVES" -- the guide's own per-practice section
# heading (all-caps short title) immediately followed by the practice
# statement, ending right where NIST SP 800-171A's own assessment
# objectives list begins. Tolerant of either the en dash the guide
# actually uses or a plain hyphen, in case a future revision's PDF
# extracts differently.
PRACTICE_RE = re.compile(
    r"([A-Z]{2}\.L1-[\d.]+)\s*[–-]\s*([A-Z0-9 &,\-]+?)\s*\n(.*?)\nASSESSMENT OBJECTIVES",
    re.DOTALL,
)


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # A couple of known pypdf extraction artifacts in this specific
    # guide: a hyphenated line-wrap ("real-\ntime") that extracts with
    # a stray space instead of collapsing, and the guide's own TOC/
    # section-heading typo for SI.L1-3.14.2's title ("Proection").
    # Fixed here, once, rather than a generic rule that could mangle
    # some other control's text differently.
    text = text.replace("real -time", "real-time")
    text = text.replace("PROECTION", "PROTECTION")  # the guide's own heading typo for SI.L1-3.14.2
    return text


def extract(pdf_path: str) -> list[dict]:
    reader = PdfReader(pdf_path)
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    seen: dict[str, dict] = {}
    for practice_id, title, statement in PRACTICE_RE.findall(full_text):
        if practice_id in seen:
            continue  # the guide repeats each section's own heading on every one of its pages
        question = clean(statement)
        title = clean(title).title()
        seen[practice_id] = {
            "Name": f"{practice_id} {title}",
            "External ID": practice_id,
            "Control ID": practice_id,
            "Statement ID": "",
            "Control Question": question,
        }
    return list(seen.values())


if __name__ == "__main__":
    rows = extract("cmmc-level-1-guide.pdf")
    out_path = "cmmc-level-1-controls.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Name", "External ID", "Control ID", "Statement ID", "Control Question"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out_path}: {len(rows)} rows")
