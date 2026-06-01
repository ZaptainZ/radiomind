"""Shared date parsing helpers for skill-level event dates.

LongMemEval session dates often look like ``2022/10/20 (Thu) 00:52``.
Several skills only need the calendar date, so this parser extracts a
front/inline date prefix without caring about weekday or time suffixes.
"""
from __future__ import annotations

import re
from datetime import datetime


_YMD_RE = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
_MONTH_RE = re.compile(
    r"\b(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
    r"(?:,\s*|\s+)"
    r"(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"],
)}


def parse_event_date(value: str) -> datetime | None:
    """Parse a calendar date from a skill event/session-date string.

    Supported shapes include:
    - ``YYYY-MM-DD``
    - ``YYYY/MM/DD``
    - ``YYYY/MM/DD (Thu) 00:52``
    - ``March 5, 2023`` / ``Mar 5, 2023``

    Returns a midnight ``datetime`` or ``None`` when no valid date is found.
    """
    if not value:
        return None
    s = str(value).strip()
    m = _YMD_RE.search(s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _MONTH_RE.search(s)
    if m:
        mon = _MONTHS.get(m.group("mon").lower()[:3])
        if not mon:
            return None
        try:
            return datetime(int(m.group("year")), mon, int(m.group("day")))
        except ValueError:
            return None
    return None
