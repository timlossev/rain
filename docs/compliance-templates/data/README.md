# Control-set data

Real register *data* (`.csv`), not config -- an Assets > Import file,
not a Config Bundle. Every CSV here has the same five columns (`Name`,
`External ID`, `Control ID`, `Statement ID`, `Control Question`)
matching `bundles/security-control-register.rain`'s own custom field
labels exactly, so Assets > Import (asset type Security Control,
format CSV) auto-suggests every column mapping -- pick the asset type,
upload the file, confirm the mapping, done. `Statement ID` is blank in
every file here: it only exists so you can later split a control you
track at a lettered-sub-part level into several rows sharing one
`Control ID`; none of the catalogs below have an official lettered
breakdown of their own.

Every `extract_*.py` script here regenerates its matching `.csv` from
the catalog's own upstream source (an official government CSV/XML
export, a vendor's free published list, or a machine-readable
standard) -- re-run one if that source ever publishes an update. None
of them need to be run to use the CSVs that already ship here; they're
only for regenerating a file, or for the one catalog (BSI's C5) whose
license doesn't permit shipping a ready-made file at all.

## Ready to import right now

No script, no download, no setup -- these seven CSVs are already
checked into this folder exactly as Assets > Import expects them:

| File | Rows | Catalog |
|---|---|---|
| `nist-800-53-rev5-low.csv` | 424 | FedRAMP Rev 5 Low baseline, one row per "response-point" |
| `nist-800-53-rev5-moderate.csv` | 688 | FedRAMP Rev 5 Moderate baseline |
| `nist-800-53-rev5-high.csv` | 791 | FedRAMP Rev 5 High baseline |
| `iso-27001-2022-annex-a-controls.csv` | 93 | All of ISO/IEC 27001:2022 Annex A (37 Organisational, 8 People, 14 Physical, 34 Technological) |
| `soc2-type2-controls.csv` | 60 | All SOC 2 Type II controls, every Trust Services Criteria (Security, Availability, Confidentiality, Processing Integrity, Privacy) |
| `cmmc-level-1-controls.csv` | 17 | CMMC Level 1 (FAR 52.204-21(b)'s basic safeguarding requirements) |
| `cmmc-level-2-controls.csv` | 110 | CMMC Level 2 -- NIST SP 800-171 Rev 2's 110 requirements, relabeled with CMMC practice IDs |
| `cmmc-level-3-controls.csv` | 24 | CMMC Level 3's *additional* practices on top of Level 2 (import both for the full 134-practice set) -- DoD's selected subset of NIST SP 800-172 |

Tracking against more than one of these at once (e.g. NIST 800-53
Moderate *and* SOC 2) is fine -- import both into the same Security
Control asset type; `Control ID` is only unique within a catalog, not
globally, so nothing collides.

## Requires running a script yourself

| Catalog | Why no ready-made CSV | What to run |
|---|---|---|
| BSI's C5:2026 | The catalogue is CC BY-ND (No Derivatives) licensed -- that withholds permission to redistribute an *adapted* version of the work, which a CSV conversion would be. Generating one for your own tenant is fine; this repo shipping one on your behalf isn't. | `extract_c5_controls.py` against your own downloaded copy of BSI's machine-readable YAML -- see the script's own docstring for the exact download URL and filename it expects. |

Every other `extract_*.py` here (`extract_fedramp_baseline.py`,
`extract_iso27001_controls.py`, `extract_soc2_controls.py`,
`extract_cmmc_level1.py`, `extract_cmmc_level2.py`,
`extract_cmmc_level3.py`) is **not** something you need to run --
their output already ships as the CSVs listed above. They exist so
the CSVs can be regenerated later (a future NIST/CMMC revision, a
corrected upstream export, ...) without hand-editing hundreds of rows;
each one's own docstring names its upstream source and the exact
filename/URL to download before running it.
