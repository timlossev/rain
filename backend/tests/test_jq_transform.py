"""rain.core.jq_transform -- the JSON export screens' optional jq-filter
step. Pure function, no DB needed (mirrors test_platform_events_matching.
py's own reasoning for why its module gets a no-DB test file)."""
from __future__ import annotations

import json

import pytest

from rain.core.jq_transform import JqTransformError, apply_jq_filter

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
