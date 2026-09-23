"""rain.core.jq_transform -- the JSON export screens' optional jq-filter
step. Pure function, no DB needed (mirrors test_platform_events_matching.
py's own reasoning for why its module gets a no-DB test file)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rain.core.jq_transform import JqTransformError, apply_jq_filter

# docs/compliance-templates, two levels up from backend/tests -- see
# test_oscal_control_implementation_template below, which runs the
# packaged transformer for real rather than just trusting it compiles.
COMPLIANCE_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "docs" / "compliance-templates"

ROWS = [
    {"Ticket Number": "INC-000001", "Severity": "high", "Title": "db down"},
    {"Ticket Number": "INC-000002", "Severity": "low", "Title": "typo on login page"},
]


def test_single_output_filter_is_used_as_is_not_wrapped():
    """map(...) produces exactly one output (the mapped array itself) --
    that should come back as the array, not a single-element list
    wrapping it, so a filter that reshapes the whole export round-trips
    as one JSON document."""
    result = apply_jq_filter(ROWS, "map({num: .[\"Ticket Number\"], sev: .Severity})")
    parsed = json.loads(result)
    assert parsed == [
        {"num": "INC-000001", "sev": "high"},
        {"num": "INC-000002", "sev": "low"},
    ]


def test_multi_output_filter_is_wrapped_in_an_array():
    """.[] produces one output per row -- several outputs, wrapped in a
    JSON array rather than left as N separate top-level values, since
    this always has to come back as exactly one JSON document to
    stream as the export's body."""
    result = apply_jq_filter(ROWS, ".[] | .Severity")
    assert json.loads(result) == ["high", "low"]


def test_zero_output_filter_is_an_empty_array():
    result = apply_jq_filter(ROWS, ".[] | select(.Severity == \"critical\")")
    assert json.loads(result) == []


def test_bare_dot_is_the_plain_export_unchanged():
    result = apply_jq_filter(ROWS, ".")
    assert json.loads(result) == ROWS


def test_invalid_syntax_raises_jq_transform_error_not_a_bare_valueerror():
    with pytest.raises(JqTransformError, match="did not compile"):
        apply_jq_filter(ROWS, "this is not [[[ valid jq")


def test_runtime_failure_raises_jq_transform_error():
    """A filter that compiles fine but fails against the actual data --
    e.g. treating a string field as a number -- is a *different* failure
    stage than a syntax error, and the error message says so."""
    with pytest.raises(JqTransformError, match="failed while running"):
        apply_jq_filter(ROWS, "map(.Severity + 1)")


def test_output_is_reindented_json_matching_render_json_style():
    """Not a strict requirement of the feature, just confirms the two
    JSON paths (filtered vs. plain exporter.render_json) produce the
    same *kind* of output -- indented, human-readable JSON, not a
    single unbroken line -- so a filtered export doesn't look
    conspicuously different from an unfiltered one for no functional
    reason."""
    result = apply_jq_filter(ROWS, ".")
    assert "\n" in result
    assert result.startswith("[\n")


def test_oscal_control_implementation_template():
    """docs/compliance-templates/oscal-control-implementation.jq, run
    against a JSON export shaped like security-control-register.rain's
    own asset type (same column headers a real export produces by
    default) -- exercises the packaged file itself, not a copy of its
    logic, so an edit that breaks it fails CI instead of only being
    caught the next time someone runs it by hand against a live
    tenant."""
    program = (COMPLIANCE_TEMPLATES_DIR / "oscal-control-implementation.jq").read_text()
    rows = [
        {
            "CI Number": "CI-000042",
            "Name": "Account Management",
            "Control ID": "AC-2",
            "Statement ID": "",
            "Implementation Status": "Implemented",
            "Narrative": "Accounts are provisioned via SSO with quarterly access review.",
            "Responsible Role": "System Owner",
            "Parameters": "Review frequency: quarterly",
            "Remarks": "",
        },
        {
            "CI Number": "CI-000043",
            "Name": "Access Enforcement part a",
            "Control ID": "AC-3",
            "Statement ID": "ac-3_smt.a",
            "Implementation Status": "Partially Implemented",
            "Narrative": "Enforced via RBAC on the tenant schema.",
            "Responsible Role": "",
            "Parameters": "",
            "Remarks": "",
        },
        {
            "CI Number": "CI-000044",
            "Name": "Access Enforcement part b",
            "Control ID": "AC-3",
            "Statement ID": "ac-3_smt.b",
            "Implementation Status": "Partially Implemented",
            "Narrative": "Session timeout enforced at 15 minutes.",
            "Responsible Role": "",
            "Parameters": "",
            "Remarks": "Compensating control pending",
        },
    ]
    result = json.loads(apply_jq_filter(rows, program))
    reqs = result["control-implementation"]["implemented-requirements"]
    assert [r["control-id"] for r in reqs] == ["ac-2", "ac-3"]

    ac2 = reqs[0]
    assert ac2["description"] == "Accounts are provisioned via SSO with quarterly access review."
    assert ac2["responsible-roles"] == [{"role-id": "system-owner"}]
    assert {"name": "implementation-status", "value": "implemented"} in ac2["props"]
    assert "statements" not in ac2  # single ungrouped row -> description, not a statements array

    ac3 = reqs[1]
    assert "description" not in ac3  # two rows sharing a control-id -> statements, not one description
    assert [s["statement-id"] for s in ac3["statements"]] == ["ac-3_smt.a", "ac-3_smt.b"]
    assert ac3["statements"][1]["remarks"] == "Compensating control pending"

    # Every uuid in the document is both present and unique -- OSCAL
    # requires global uniqueness, and this file's whole approach to
    # generating them (zero-padding each row's own CI Number rather
    # than a real UUID) is exactly the kind of thing that silently
    # collides if a future edit gets the slicing wrong.
    uuids = [ac2["uuid"]] + [s["uuid"] for s in ac3["statements"]] + [ac3["uuid"]]
    assert len(uuids) == len(set(uuids))
    for u in uuids:
        assert len(u) == 36 and u.count("-") == 4
