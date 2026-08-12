from __future__ import annotations

import enum
from typing import Any


class FieldType(str, enum.Enum):
    text = "text"
    number = "number"
    boolean = "boolean"
    date = "date"
    url = "url"
    email = "email"
    select = "select"


def coerce_field_value(field_type: str, raw: str | None) -> Any:
    """Convert a raw string (HTML form field or CSV/JSON cell) into the
    JSONB-storable value for a custom field, per its declared type."""
    if raw is None or raw == "":
        return None
    if field_type == FieldType.number.value:
        try:
            return int(raw)
        except ValueError:
            try:
                return float(raw)
            except ValueError:
                return raw
    if field_type == FieldType.boolean.value:
        return str(raw).strip().lower() in ("1", "true", "on", "yes")
    return str(raw)
