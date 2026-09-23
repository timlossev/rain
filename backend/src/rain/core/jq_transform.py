"""Optional jq-filter transform step for the JSON export screens
(Tickets, Assets) -- python-jq (a musllinux-wheel-vendored libjq, no
system library or Dockerfile change needed; see pyproject.toml's own
comment on this dependency) applied to the export's already-built row
list, so a tenant can reshape RAIN's flat column-picker output into
whatever JSON shape a downstream consumer actually expects, instead of
post-processing the plain export by hand every time. The filter's own
source text comes from wherever the export route resolved it (an
uploaded .jq file for this one run, or a saved Document's own body --
see rain.modules.tickets.router/rain.modules.assets.router's shared
_resolve_jq_filter_text) -- this module only ever runs it, it doesn't
know or care where the text came from.
"""
from __future__ import annotations

import json
from typing import Any

import jq


class JqTransformError(ValueError):
    """Wraps jq's own bare ValueError (both jq.compile() and a compiled
    program's .all() raise that same type, for a bad filter and a
    runtime failure respectively -- e.g. dividing by zero) with a label
    naming which half of the pipeline actually failed, since the export
    form needs to tell a tenant *that* much, not just that their filter
    "didn't work"."""


def apply_jq_filter(rows: list[dict[str, Any]], filter_program: str) -> str:
    """Runs `filter_program` against `rows` as one JSON input document
    and returns the result re-serialized as indented JSON text -- the
    same shape exporter.render_json() already produces with no filter
    set, so this is a drop-in replacement for the plain export, not a
    second output format alongside it.

    A jq program can emit zero, one, or several outputs for one input
    (`.[] | select(...)`, say) -- `.compile(...).input_value(rows).all()`
    always returns a list of whatever it produced. Exactly one output is
    used as-is (the common case: `map(...)`, a `{...}` object
    constructor, a bare `.`) so a filter that reshapes the whole row
    list into one document round-trips as that one document, not a
    single-element array wrapping it; zero or several outputs are left
    as a JSON array of whatever came out, the same convention the `jq`
    CLI's own multi-document stdout implies when a filter produces more
    than one JSON value."""
    try:
        program = jq.compile(filter_program)
    except ValueError as exc:
        raise JqTransformError(f"jq filter did not compile: {exc}") from exc
    try:
        results = program.input_value(rows).all()
    except ValueError as exc:
        raise JqTransformError(f"jq filter failed while running: {exc}") from exc
    output = results[0] if len(results) == 1 else results
    return json.dumps(output, indent=2, default=str)
