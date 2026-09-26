"""Turns BSI's Cloud Computing Compliance Controls Catalogue (C5:2026)
machine-readable YAML into the same import-ready CSV shape the FedRAMP/
ISO 27001/SOC 2 kits use: https://www.bsi.bund.de/SharedDocs/Downloads/EN/
BSI/CloudComputing/ComplianceControlsCatalogue/2026/C5_machine_readable.zip

Unlike those three, this script's *output* isn't checked into the repo --
only the script is. The C5 catalogue is licensed CC BY-ND 4.0 (Attribution-
NoDerivatives): https://creativecommons.org/licenses/by-nd/4.0/. ND
specifically withholds permission to distribute an adapted version of the
work, and a CSV reformatting BSI's own requirement text into RAIN's column
shape is exactly that -- fine to generate and import into your own tenant
(private use isn't what ND restricts), not fine for this repo to commit
and push to GitHub on your behalf. Run this yourself against your own
downloaded copy instead; see docs/compliance-templates/README.md for the
reasoning and the rest of this usage note.

Expects the zip's *_Machine-Readable_en folder extracted next to this
script (one YAML file per control domain -- AM.yml, BCM.yml, COM.yml,
COS.yml, CRY.yml, DEV.yml, GC.yml, HR.yml, IAM.yml, INQ.yml, OIS.yml,
OPS.yml, PI.yml, PS.yml, PSS.yml, SIM.yml, SP.yml, SSO.yml --
version_and_license.yml is metadata, not controls, and is skipped).

Each domain file is a list of top-level criteria, each carrying a
`basic` list of sub-criteria and (often empty) `additional_sharpen`/
`additional_complement` lists of further sub-criteria -- structurally
the same "one control, several lettered statement parts" shape
FedRAMP's OSCAL catalog has, just YAML instead of XML and BSI's own
alphanumeric identifiers (e.g. "01B", "01AS", "01AC") instead of OSCAL's
"ac-2_smt.a". Each sub-criterion's own `criterion` text is what becomes
Control Question here; the `information` key some top-level criteria
carry is supplementary implementation guidance covering several sub-
criteria at once, not a per-row control statement, so it's left out --
same reasoning FedRAMP's own extractor drops <guidance> for.

Requires PyYAML (`pip install pyyaml`) -- not a RAIN backend dependency
(nothing at runtime parses YAML), so install it in whatever environment
you run this script from.

Usage: unzip C5_machine_readable.zip next to this script (so
C5_2026_Machine-Readable_en/DEV.yml etc. exist alongside it), then run
`python3 extract_c5_controls.py`.
"""
from __future__ import annotations

import csv
import glob
import os
import re

import yaml

FOLDER_GLOB = "C5_*_Machine-Readable_en"
SKIP_FILES = {"version_and_license.yml"}


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def domain_code(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def extract_domain(path: str) -> list[dict]:
    domain = domain_code(path)
    entries = yaml.safe_load(open(path, encoding="utf-8")) or []
    rows = []
    for entry in entries:
        # GC.yml (General Conditions -- transparency requirements the
        # cloud provider discloses, not a technical control) is a flat
        # {id, name, condition, hint} list, its own id already fully
        # formed ("GC-01"); every other domain nests Basic/Additional-
        # Sharpen/Additional-Complement sub-criteria under a top-level
        # criterion the way FedRAMP nests lettered statement parts
        # under a control.
        if "condition" in entry:
            rows.append({
                "Name": f"{entry['id']} {clean(entry.get('name'))}",
                "External ID": entry["id"],
                "Control ID": entry["id"],
                "Statement ID": "",
                "Control Question": clean(entry.get("condition")),
            })
            continue

        control_id = f"{domain}-{entry['identifier']}"
        title = clean(entry.get("name"))
        for sub_items in (entry.get("basic"), entry.get("additional_sharpen"), entry.get("additional_complement")):
            for item in sub_items or []:
                statement_id = item["identifier"]
                rows.append({
                    "Name": f"{control_id}({statement_id}) {title}",
                    "External ID": f"{control_id}.{statement_id}",
                    "Control ID": control_id,
                    "Statement ID": statement_id,
                    "Control Question": clean(item.get("criterion")),
                })
    return rows


if __name__ == "__main__":
    folders = glob.glob(FOLDER_GLOB)
    if not folders:
        raise SystemExit(f"No {FOLDER_GLOB} folder found next to this script -- unzip C5_machine_readable.zip here first.")

    rows = []
    for domain_file in sorted(glob.glob(os.path.join(folders[0], "*.yml"))):
        if os.path.basename(domain_file) in SKIP_FILES:
            continue
        rows.extend(extract_domain(domain_file))

    out_path = "c5-2026-controls.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Name", "External ID", "Control ID", "Statement ID", "Control Question"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out_path}: {len(rows)} rows")
