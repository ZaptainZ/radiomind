"""Temporal / date-arithmetic helper for retrieval answer-synthesis.

Problem this solves: LongMemEval temporal-reasoning sits at 0.15-0.30 because
the LLM must compute "how many days ago" / "between X and Y" in its head,
and naked Qwen/GPT are 60-70% accurate on date arithmetic. We can be 100%
accurate cheaply.

Strategy:
- Detect temporal questions (reuses pyramid's _TEMPORAL_QUERY_MARKERS spirit).
- Parse the "now" date (caller provides it — in LongMemEval it's the
  per-question `question_date`).
- Parse event dates out of retrieved entries' `metadata.session_date` and
  any inline dates in the content.
- Emit a small structured preamble the answer prompt can use:
    "[COMPUTED] Event 'bought smoker' was 10 days ago (2025-09-12, now 2025-09-22)."

The LLM still writes the final sentence — we just hand it the arithmetic.
"""
from __future__ import annotations

import re
from datetime import datetime

_TEMPORAL_MARKERS = (
    "how many days ago", "how many weeks ago", "how many months ago",
    "how many years ago", "how long ago", "days passed between",
    "weeks passed between", "months passed between",
    "how many days did", "how many weeks did", "how many months did",
    "how long did", "how long have", "how long was",
    "多久以前", "多长时间", "几天前", "几个月前", "几年前", "之间",
)


_DATE_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DATE_SLASH = re.compile(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b")
_DATE_INLINE = re.compile(
    r"\b(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?P<d>\d{1,2})(?:[,\s]+(?P<y>\d{4}))?\b",
    re.IGNORECASE,
)
_MON_NUM = {m: i + 1 for i, m in enumerate([
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
])}


def is_temporal_question(q: str) -> bool:
    ql = q.lower()
    return any(m in ql for m in _TEMPORAL_MARKERS)


def parse_date(s: str, default_year: int | None = None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    for pat in (_DATE_ISO, _DATE_SLASH):
        m = pat.search(s)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    m = _DATE_INLINE.search(s)
    if m:
        mon = _MON_NUM.get(m.group("mon").lower()[:3])
        d = int(m.group("d"))
        y = int(m.group("y")) if m.group("y") else default_year
        if mon and y:
            try:
                return datetime(y, mon, d)
            except ValueError:
                pass
    return None


def compute_deltas(
    now: str,
    retrieved: list[tuple[str, str]],
    max_facts: int = 5,
) -> list[str]:
    """Given (content, session_date) pairs, emit pre-computed delta facts.

    retrieved: list of (content_text, session_date_str) from top-k results.
    Returns strings like "(2025-09-12, 10 days before 2025-09-22)" that
    the answer-synthesis prompt can paste in.
    """
    now_dt = parse_date(now)
    if now_dt is None:
        return []
    emitted: list[str] = []
    seen_dates: set[str] = set()
    for content, sdate in retrieved[:20]:
        dt = parse_date(sdate, default_year=now_dt.year)
        if dt is None:
            # Try content's inline date as fallback
            dt = parse_date(content, default_year=now_dt.year)
        if dt is None:
            continue
        key = dt.strftime("%Y-%m-%d")
        if key in seen_dates:
            continue
        seen_dates.add(key)
        days = (now_dt - dt).days
        if days < 0:
            continue
        # Surface both days and months for the LLM to pick whichever
        # the question asks for. Approximate months as days/30.4.
        months = days / 30.4
        if days < 60:
            label = f"{days} days ago"
        elif months < 24:
            label = f"{days} days ago (≈{months:.1f} months ago)"
        else:
            label = f"{days} days ago (≈{months/12:.1f} years ago)"
        emitted.append(f"[{key}] = {label}")
        if len(emitted) >= max_facts:
            break
    return emitted
