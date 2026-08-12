"""Minimal iCalendar (.ics, RFC 5545) export/import -- just enough to
round-trip RAIN calendar entries with common calendar apps (Outlook,
Google Calendar, Apple Calendar) and with RAIN's own export. Not a full
RFC 5545 implementation (no line unfolding across continuation lines, no
timezone-aware DTSTART, only VEVENT/SUMMARY/DESCRIPTION/DTSTART/RRULE/a
custom X-RAIN-POLICY property) -- good enough for all-day, single-rule
recurring entries, which is all this app ever writes.

X-RAIN-POLICY carries CalendarEntry.policy_ref (the currently-inert
"future hook for rule policies" field) through export and back on
import, as a JSON blob, so nothing is lost round-tripping through an
external calendar app even though nothing acts on it yet."""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

_RRULE_FREQ = {
    "quarterly": "FREQ=MONTHLY;INTERVAL=3",
    "biannual": "FREQ=MONTHLY;INTERVAL=6",
    "annual": "FREQ=YEARLY",
}


def _escape_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _unescape_text(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def export_ics(entries: list[Any], *, instance_name: str) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//RAIN//{_escape_text(instance_name)}//EN"]
    for e in entries:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:rain-calendar-entry-{e.id}@rain")
        lines.append(f"DTSTART;VALUE=DATE:{e.start_date.strftime('%Y%m%d')}")
        lines.append(f"SUMMARY:{_escape_text(e.title)}")
        if e.description:
            lines.append(f"DESCRIPTION:{_escape_text(e.description)}")
        if e.recurrence in _RRULE_FREQ:
            rrule = _RRULE_FREQ[e.recurrence]
            if e.recurrence_end:
                rrule += f";UNTIL={e.recurrence_end.strftime('%Y%m%d')}"
            lines.append(f"RRULE:{rrule}")
        if e.policy_ref:
            lines.append(f"X-RAIN-POLICY:{_escape_text(json.dumps(e.policy_ref))}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def parse_ics(content: str) -> list[dict[str, Any]]:
    """Returns a list of dicts shaped like CalendarEntry constructor kwargs
    (title, start_date, description=, recurrence=, recurrence_end=,
    policy_ref=) -- one per VEVENT that had at least a SUMMARY and DTSTART."""
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current and "title" in current and "start_date" in current:
                entries.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.split(";")[0]  # drop parameters, e.g. DTSTART;VALUE=DATE

        if key == "SUMMARY":
            current["title"] = _unescape_text(value)
        elif key == "DESCRIPTION":
            current["description"] = _unescape_text(value)
        elif key == "DTSTART":
            digits = re.sub(r"[^0-9]", "", value)[:8]
            if len(digits) == 8:
                current["start_date"] = dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        elif key == "RRULE":
            params = dict(part.split("=", 1) for part in value.split(";") if "=" in part)
            freq, interval = params.get("FREQ"), params.get("INTERVAL", "1")
            if freq == "YEARLY":
                current["recurrence"] = "annual"
            elif freq == "MONTHLY" and interval == "6":
                current["recurrence"] = "biannual"
            elif freq == "MONTHLY" and interval == "3":
                current["recurrence"] = "quarterly"
            if "UNTIL" in params:
                digits = re.sub(r"[^0-9]", "", params["UNTIL"])[:8]
                if len(digits) == 8:
                    current["recurrence_end"] = dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        elif key == "X-RAIN-POLICY":
            try:
                current["policy_ref"] = json.loads(_unescape_text(value))
            except ValueError:
                pass
    return entries
