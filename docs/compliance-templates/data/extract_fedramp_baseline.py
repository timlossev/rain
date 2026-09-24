"""Regenerates nist-800-53-rev5-{low,moderate,high}.csv from the real
FedRAMP Rev 5 baselines, published as resolved OSCAL catalog XML by
oscal-compass/compliance-trestle-fedramp:
https://github.com/oscal-compass/compliance-trestle-fedramp/tree/develop/trestle_fedramp/resources/fedramp-source/content/baselines/rev5/xml

One CSV row per FedRAMP "response-point" -- a custom prop FedRAMP's own
resolved catalog uses to mark exactly the statement parts an SSP author
is expected to answer (confirmed by inspection: always on the bare
statement part itself, for a control with no lettered sub-items, or on
its direct lettered 'item' children -- never deeper, so no recursive
search is needed to find them). Column headers match
security-control-register.rain's own custom field labels exactly, so
Assets > Import auto-suggests every mapping.

Usage: download the three "*-baseline-resolved-profile_catalog.xml"
files from the URL above as low.xml/moderate.xml/high.xml next to this
script, then run `python3 extract_fedramp_baseline.py`.
"""
from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET

NS = {"o": "http://csrc.nist.gov/ns/oscal/1.0"}


def q(tag: str) -> str:
    return f"{{{NS['o']}}}{tag}"


def build_parent_map(root):
    return {c: p for p in root.iter() for c in p}


def part_text(part, param_labels: dict[str, str]) -> str:
    """Concatenated human-readable text of a part: its own <p>, plus every
    descendant item part's own label-prefixed <p>, in document order --
    <insert type="param" id-ref="X"> resolved to "[label text]" from this
    control's own <param> definitions (still an org-defined placeholder in
    the FedRAMP baseline itself, not a concrete value -- that's the CSP's
    own job when they answer it)."""
    chunks = []

    def walk(p, top=True):
        label_el = p.find(f"./{q('prop')}[@name='label']")
        label = label_el.get("value") if label_el is not None else None
        direct_p = p.find(f"./{q('p')}")
        if direct_p is not None:
            text = render_p(direct_p, param_labels)
            chunks.append(f"{label} {text}" if label and not top else text)
        for child in p.findall(f"./{q('part')}"):
            if child.get("name") == "item":
                walk(child, top=False)

    walk(part, top=True)
    return " ".join(c.strip() for c in chunks if c and c.strip())


def render_p(p_el, param_labels: dict[str, str]) -> str:
    out = [p_el.text or ""]
    for child in p_el:
        tag = child.tag.split("}")[-1]
        if tag == "insert" and child.get("type") == "param":
            out.append(f"[{param_labels.get(child.get('id-ref'), child.get('id-ref'))}]")
        else:
            out.append("".join(child.itertext()))
        out.append(child.tail or "")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def response_point_parts(stmt):
    found = []
    if stmt.find(f"./{q('prop')}[@name='response-point']") is not None:
        found.append(stmt)
    for item in stmt.findall(f"./{q('part')}"):
        if item.get("name") == "item" and item.find(f"./{q('prop')}[@name='response-point']") is not None:
            found.append(item)
    return found


def extract(xml_path: str) -> list[dict]:
    root = ET.parse(xml_path).getroot()
    rows = []

    for control in root.findall(f".//{q('control')}"):
        cid = control.get("id")
        title_el = control.find(f"./{q('title')}")
        title = title_el.text if title_el is not None else ""

        param_labels: dict[str, str] = {}
        for param in control.findall(f"./{q('param')}"):
            label_el = param.find(f"./{q('label')}")
            if label_el is not None and label_el.text:
                param_labels[param.get("id")] = label_el.text
                continue
            select_el = param.find(f"./{q('select')}")
            if select_el is not None:
                choices = [c.text for c in select_el.findall(f"./{q('choice')}") if c.text]
                if choices:
                    param_labels[param.get("id")] = " | ".join(choices)

        stmt = control.find(f"./{q('part')}[@name='statement']")
        if stmt is None:
            continue  # a handful of controls (e.g. withdrawn ones) have no statement to answer

        for part in response_point_parts(stmt):
            pid = part.get("id") or ""
            is_bare = pid == f"{cid}_smt"
            rows.append({
                "control_id": cid,
                "title": title,
                "statement_id": "" if is_bare else pid,
                "question": part_text(part, param_labels),
            })
    return rows


def import_ready_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        cid, sid = r["control_id"], r["statement_id"]
        letter = sid.rsplit(".", 1)[-1] if sid else ""
        name = f"{cid.upper()}({letter}) {r['title']}" if letter else f"{cid.upper()} {r['title']}"
        out.append({
            "Name": name,
            "External ID": sid or cid,
            "Control ID": cid,
            "Statement ID": sid,
            "Control Question": r["question"],
        })
    return out


if __name__ == "__main__":
    for baseline in ["low", "moderate", "high"]:
        rows = import_ready_rows(extract(f"{baseline}.xml"))
        out_path = f"nist-800-53-rev5-{baseline}.csv"
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["Name", "External ID", "Control ID", "Statement ID", "Control Question"])
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {out_path}: {len(rows)} rows")
