"""Shared helper for the Assets/Tickets export screens' column table:
merges a saved ExportProfile's columns back onto the current available
column list (both expressed as the same (source, label) shape) so
export.html can render checkboxes/headers/order pre-filled for a loaded
profile. A column newly available since the profile was saved (schema
drift -- a new custom field, say) is appended unchecked rather than
silently dropped."""
from __future__ import annotations


def merge_profile_columns(
    available: list[tuple[str, str]], profile_columns: list[dict] | None
) -> list[dict]:
    if not profile_columns:
        return [{"source": s, "header": h, "order": i, "checked": True} for i, (s, h) in enumerate(available)]
    saved = {c["source"]: c for c in profile_columns}
    rows = []
    next_order = len(profile_columns)
    for source, label in available:
        if source in saved:
            c = saved[source]
            rows.append(
                {"source": source, "header": c.get("header", label), "order": c.get("order", 0), "checked": True}
            )
        else:
            rows.append({"source": source, "header": label, "order": next_order, "checked": False})
            next_order += 1
    rows.sort(key=lambda r: r["order"])
    return rows
