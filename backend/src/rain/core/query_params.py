"""One tiny helper: turning an optional integer query param that might
arrive as an empty string into a real `int | None`.
"""
from __future__ import annotations


def optional_int(value: str | None) -> int | None:
    """FastAPI/Pydantic reject an `int | None` query param outright (a raw
    422, not a clean "not provided") the moment it arrives as an empty
    string -- but an empty string is exactly what a plain `<select>`'s
    "clear" option (`value=""`) or `_search_picker.html`'s own always-
    present hidden input actually submits once a filter is cleared or
    never picked, not just omitted from the URL entirely. Confirmed live:
    clearing "group by assignee"'s team filter, or the tickets/documents
    asset/owner picker, 500'd instead of falling back to "no filter".

    Typing the affected param `str | None` and parsing it through this at
    the top of the route (reusing the same name, e.g. `asset_id =
    optional_int(asset_id)`) is what makes clearing a dropdown mean "no
    filter" again instead of a raw validation-error page."""
    return int(value) if value else None
