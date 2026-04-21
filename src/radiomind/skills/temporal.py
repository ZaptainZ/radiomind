"""Temporal arithmetic skill.

Handles relative offsets, duration between events, absolute date lookups
using session_date metadata + reference_date. No LLM call.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from radiomind.skills.base import Skill, SkillResult


_UNIT_DAYS = {
    "day": 1, "days": 1,
    "week": 7, "weeks": 7,
    "month": 30, "months": 30,
    "year": 365, "years": 365,
    "hour": 1 / 24.0, "hours": 1 / 24.0,
}

_AGO_RE = re.compile(
    r"how\s+(?:many|much)\s+(days?|weeks?|months?|years?|hours?)\s+ago\s+"
    r"(?:did|was|were|have)\s+(.+?)[\?\.\!]?$",
    re.IGNORECASE,
)
_BETWEEN_RE = re.compile(
    r"how\s+many\s+(days?|weeks?|months?|years?)\s+"
    r"(?:passed\s+)?between\s+(?:the\s+day\s+)?(.+?)\s+and\s+"
    r"(?:the\s+day\s+)?(.+?)[\?\.\!]?$",
    re.IGNORECASE,
)
_SINCE_RE = re.compile(
    r"how\s+(?:long|many\s+(?:days|weeks|months|years))\s+"
    r"(?:has\s+it\s+been\s+)?(?:since|after)\s+(.+?)[\?\.\!]?$",
    re.IGNORECASE,
)


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s[: len(fmt) + 10], fmt)
        except ValueError:
            continue
    return None


def _phrase_tokens(phrase: str) -> list[str]:
    stop = {
        "the", "a", "an", "i", "my", "you", "your", "at", "in", "on",
        "for", "to", "of", "and", "or", "with", "from", "did", "had",
        "have", "was", "were", "do", "does", "is", "are", "been",
    }
    return [
        t for t in re.findall(r"[a-z0-9]+", (phrase or "").lower())
        if len(t) > 2 and t not in stop
    ]


def _match_phrase(content: str, phrase: str) -> float:
    tokens = _phrase_tokens(phrase)
    if not tokens:
        return 0.0
    low = (content or "").lower()
    hits = sum(1 for t in tokens if t in low)
    return hits / len(tokens)


def _find_event_date(
    phrase: str, memories: list, threshold: float = 0.4,
) -> datetime | None:
    """Scan memories for best date match. Prefer temporal_anchor entries.

    Lowered threshold from 0.6 to 0.4 because the phrase LLM captures is
    often a short fragment ("FarmFresh subscription") that won't have
    60%+ tokens in a real memory ("I decided to cancel my FarmFresh").
    Too strict → skill never fires → trinity hallucinates dates.
    """
    best: tuple[float, datetime] | None = None
    # Two passes: anchor entries first, then general memories
    anchor_first: list[tuple[Any, bool]] = []
    for m in memories:
        if hasattr(m, "entry"):
            meta = m.entry.metadata or {}
            is_anchor = meta.get("kind") == "temporal_anchor"
            anchor_first.append((m, is_anchor))
        elif isinstance(m, dict):
            is_anchor = m.get("kind") == "temporal_anchor"
            anchor_first.append((m, is_anchor))
    anchor_first.sort(key=lambda x: not x[1])

    for m, is_anchor in anchor_first:
        if hasattr(m, "entry"):
            sdate = (m.entry.metadata or {}).get("event_date") or \
                    (m.entry.metadata or {}).get("session_date", "")
            content = m.entry.content or ""
        else:
            sdate = m.get("event_date") or m.get("created_at") or m.get("session_date", "")
            content = m.get("memory") or m.get("content") or ""
        if not sdate:
            continue
        score = _match_phrase(content, phrase)
        if is_anchor:
            score += 0.2  # anchor bonus
        if score < threshold:
            continue
        d = _parse_date(sdate)
        if not d:
            continue
        if best is None or score > best[0]:
            best = (score, d)
    return best[1] if best else None


def _format_offset(delta_days: float, unit: str) -> str:
    u = unit.lower().rstrip("s")
    per = _UNIT_DAYS.get(u + "s") or _UNIT_DAYS.get(u) or 1
    value = round(delta_days / per)
    plural = "s" if abs(value) != 1 else ""
    return f"{value} {u}{plural}"


class TemporalSkill(Skill):
    name = "temporal"
    priority = 10

    def match(self, signature: Any) -> bool:
        wants = getattr(signature, "wants", "")
        return wants == "date"

    def resolve(self, query: str, memories: list, context: dict) -> SkillResult | None:
        ref_str = context.get("reference_date") or ""
        ref = _parse_date(ref_str)

        # Shape: "between A and B"
        m = _BETWEEN_RE.search(query)
        if m:
            unit = m.group(1)
            a = _find_event_date(m.group(2), memories)
            b = _find_event_date(m.group(3), memories)
            if a and b:
                delta = abs((b - a).days)
                return SkillResult(
                    skill_name=self.name,
                    answer=_format_offset(delta, unit),
                    anchors=[
                        (m.group(2).strip(), a.strftime("%Y-%m-%d")),
                        (m.group(3).strip(), b.strftime("%Y-%m-%d")),
                    ],
                )

        # Shape: "how many X ago did Y"
        m = _AGO_RE.search(query)
        if m and ref:
            unit = m.group(1)
            phrase = m.group(2).strip()
            event = _find_event_date(phrase, memories)
            if event and ref >= event:
                delta = (ref - event).days
                return SkillResult(
                    skill_name=self.name,
                    answer=f"{_format_offset(delta, unit)} ago",
                    anchors=[(phrase, event.strftime("%Y-%m-%d"))],
                )

        # Shape: "how long since Y"
        m = _SINCE_RE.search(query)
        if m and ref:
            phrase = m.group(1).strip()
            event = _find_event_date(phrase, memories)
            if event and ref >= event:
                delta = (ref - event).days
                return SkillResult(
                    skill_name=self.name,
                    answer=f"{_format_offset(delta, 'days')} since {phrase}",
                    anchors=[(phrase, event.strftime("%Y-%m-%d"))],
                )

        return None


# Auto-register
from radiomind.skills.registry import register  # noqa: E402

register(TemporalSkill())
