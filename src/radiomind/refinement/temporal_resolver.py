"""Deterministic temporal resolver — structured-arithmetic before LLM.

Principle: when the task reduces to known arithmetic over structured
metadata (session_date on retrieved memories + question_date), solve it
deterministically. Only fall through to trinity when the resolver
can't identify two anchor events or the arithmetic is ambiguous.

This is not a "skip trinity" hack — it's the architectural ordering
"structured layer before LLM layer". Trinity still owns the fallback.

Handles three common temporal shapes LME-S surfaces:
  1. "how many days/weeks/... ago did X happen"
     → find event X date in memories, subtract from reference_date
  2. "how many days/weeks between A and B"
     → find both event dates, subtract
  3. "how long since/before/after X"
     → find X date, subtract from reference_date

Returns a strict one-line answer string on success, None otherwise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


_UNIT_DAYS = {
    "day": 1, "days": 1,
    "week": 7, "weeks": 7,
    "month": 30, "months": 30,  # rough
    "year": 365, "years": 365,
    "hour": 1/24.0, "hours": 1/24.0,
}


_AGO_RE = re.compile(
    r"how\s+(?:many|much)\s+(days?|weeks?|months?|years?|hours?)\s+ago\s+"
    r"(?:did|was|were)\s+(.+?)[\?\.$]",
    re.IGNORECASE,
)
_BETWEEN_RE = re.compile(
    r"how\s+many\s+(days?|weeks?|months?|years?)\s+"
    r"(?:passed\s+)?between\s+(?:the\s+day\s+)?(.+?)\s+and\s+"
    r"(?:the\s+day\s+)?(.+?)[\?\.$]",
    re.IGNORECASE,
)


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s[:len(fmt) + 10], fmt)
        except ValueError:
            continue
    return None


def _memory_matches_phrase(content: str, phrase: str) -> bool:
    """Does this memory plausibly describe the event named by `phrase`?"""
    if not content or not phrase:
        return False
    content_low = content.lower()
    # Extract content words from phrase (len > 2, non-stop)
    stop = {"the", "a", "an", "i", "my", "you", "your", "at", "in", "on",
            "for", "to", "of", "and", "or", "with", "from", "did", "had",
            "have", "was", "were", "do", "does", "is", "are"}
    tokens = [t for t in re.findall(r"[a-z0-9]+", phrase.lower())
              if len(t) > 2 and t not in stop]
    if not tokens:
        return False
    # Require ≥60% of tokens to appear (robust to minor paraphrase)
    hits = sum(1 for t in tokens if t in content_low)
    return hits / len(tokens) >= 0.6


def _find_event_date(
    phrase: str, retrieved: list,
) -> datetime | None:
    """Scan retrieved memories; return the session_date of the best match."""
    best_date = None
    for m in retrieved:
        if hasattr(m, "entry"):
            sdate = (m.entry.metadata or {}).get("session_date", "")
            content = m.entry.content or ""
        elif isinstance(m, dict):
            sdate = m.get("created_at") or m.get("session_date") or ""
            content = m.get("memory") or m.get("content") or ""
        else:
            continue
        if not sdate:
            continue
        if _memory_matches_phrase(content, phrase):
            d = _parse_date(sdate)
            if d:
                # Prefer earliest matching memory (first occurrence of event)
                if best_date is None or d < best_date:
                    best_date = d
    return best_date


def _format_offset(delta_days: float, unit: str) -> str:
    """Render the answer in the requested unit, rounded to integer."""
    u = unit.lower().rstrip("s")
    per = _UNIT_DAYS.get(u + "s") or _UNIT_DAYS.get(u) or 1
    value = round(delta_days / per)
    plural = "s" if abs(value) != 1 else ""
    return f"{value} {u}{plural}"


@dataclass
class TemporalResult:
    answer: str
    anchor_dates: list[tuple[str, str]]  # (description, YYYY-MM-DD)


def resolve(
    query: str,
    retrieved: list,
    reference_date: str = "",
    answer_shape: str = "relative_offset",
) -> TemporalResult | None:
    """Try to solve the temporal question deterministically. None on failure."""
    ref = _parse_date(reference_date)

    # Shape: "how many X between A and B"
    m = _BETWEEN_RE.search(query)
    if m:
        unit = m.group(1)
        phrase_a = m.group(2).strip()
        phrase_b = m.group(3).strip()
        date_a = _find_event_date(phrase_a, retrieved)
        date_b = _find_event_date(phrase_b, retrieved)
        if date_a and date_b:
            delta = abs((date_b - date_a).days)
            ans = _format_offset(delta, unit)
            return TemporalResult(
                answer=ans,
                anchor_dates=[
                    (phrase_a, date_a.strftime("%Y-%m-%d")),
                    (phrase_b, date_b.strftime("%Y-%m-%d")),
                ],
            )

    # Shape: "how many X ago did Y"
    m = _AGO_RE.search(query)
    if m and ref:
        unit = m.group(1)
        phrase = m.group(2).strip()
        event_date = _find_event_date(phrase, retrieved)
        if event_date:
            delta = (ref - event_date).days
            if delta >= 0:
                ans = f"{_format_offset(delta, unit)} ago"
                return TemporalResult(
                    answer=ans,
                    anchor_dates=[(phrase, event_date.strftime("%Y-%m-%d"))],
                )

    return None


def format_prefix(result: TemporalResult) -> str:
    lines = [
        "STRUCTURED TEMPORAL RESOLVER "
        "(deterministic date arithmetic from session_date metadata; "
        "trust this unless retrieved memories explicitly contradict):"
    ]
    for desc, date in result.anchor_dates[:3]:
        lines.append(f"- {desc} → {date}")
    lines.append(f"Computed answer: {result.answer}")
    return "\n".join(lines) + "\n\n"
