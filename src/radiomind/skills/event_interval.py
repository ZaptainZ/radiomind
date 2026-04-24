"""Event-interval skill — weeks/months/years between two dated events.

Handles questions of the shape:
  - "How many weeks have I been X-ing when I Y-ed?"
  - "How many months between my X and my Y?"
  - "How long since my first X when I did Y?"

Two anchor events A and B must be located in memories, each mapped to a
date. The answer is |date_B − date_A| converted to the question's unit
(weeks / months / years / days).

Distinct from age_interval (which handles 1 event + current age diff)
and temporal (which handles 1 phrase + a reference date). This one is
event-to-event.

Strategy (mirrors age_interval's three-tier fallback):
  1. Token-match on each phrase against retrieved memories; prefer
     entries with explicit dates.
  2. Trinity semantic escalation for each missing anchor — the LLM
     finds the best-matching memory even under paraphrase
     ("started sculpting class" ↔ "just began sculpting").
  3. Full-store FACT scan as last resort.
Trinity validates the final interval before committing.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from radiomind.skills.base import Skill, SkillResult


# "How many weeks/months/days"
_INTERVAL_UNIT_RE = re.compile(
    r"how\s+many\s+(weeks?|months?|years?|days?)",
    re.IGNORECASE,
)

# Shape A: "how many weeks have I been X-ing when/before I Y-ed"
#   group 1 = unit; group 2 = A phrase; group 3 = B phrase
_A_BEEN_WHEN_RE = re.compile(
    r"how\s+many\s+(weeks?|months?|years?|days?)\s+(?:have\s+|had\s+)?I\s+been\s+"
    r"(.+?)\s+(?:when|before|after)\s+I\s+(.+?)(?:\?|$|\.)",
    re.IGNORECASE,
)

# Shape B: "how many weeks between my X and my Y"
_BETWEEN_RE = re.compile(
    r"how\s+many\s+(weeks?|months?|years?|days?)\s+(?:passed\s+|went\s+by\s+)?"
    r"between\s+(?:my\s+|the\s+)?(.+?)\s+and\s+(?:my\s+|the\s+)?(.+?)(?:\?|$|\.)",
    re.IGNORECASE,
)

# Shape C: "how many weeks since my X when I did Y"
_SINCE_WHEN_RE = re.compile(
    r"how\s+many\s+(weeks?|months?|years?|days?)\s+(?:had\s+)?passed\s+since\s+I\s+"
    r"(.+?)\s+when\s+I\s+(.+?)(?:\?|$|\.)",
    re.IGNORECASE,
)


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y")
_YMD_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    m = _YMD_RE.search(s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s[: len(fmt) + 4], fmt)
        except ValueError:
            continue
    return None


def _unit_to_days(unit: str) -> int:
    u = unit.lower().rstrip("s")
    return {"day": 1, "week": 7, "month": 30, "year": 365}.get(u, 1)


def _find_event_mentions(
    phrase: str, memories: list, limit: int = 6,
) -> list[tuple[str, str]]:
    """[(content, date)] for memories with significant token overlap
    AND an extractable date."""
    stop = {"the", "a", "an", "i", "my", "was", "were", "from", "to", "at",
            "on", "in", "of", "for", "with", "and", "or", "but"}
    tokens = [
        t for t in re.findall(r"[a-z0-9]+", (phrase or "").lower())
        if len(t) > 2 and t not in stop
    ]
    if not tokens:
        return []
    hits: list[tuple[float, str, str]] = []
    for m in memories[:80]:
        if hasattr(m, "entry"):
            meta = m.entry.metadata or {}
            sdate = meta.get("event_date") or meta.get("session_date", "")
            content = m.entry.content or ""
        elif isinstance(m, dict):
            sdate = m.get("event_date") or m.get("created_at") or m.get("session_date", "")
            content = m.get("memory") or m.get("content") or ""
        else:
            continue
        if not sdate:
            continue
        low = content.lower()
        score = sum(1 for t in tokens if t in low) / len(tokens)
        if score >= 0.5:
            hits.append((score, content[:200], str(sdate)))
    hits.sort(key=lambda x: -x[0])
    return [(c, d) for _, c, d in hits[:limit]]


def _find_event_via_trinity(
    phrase: str, memories: list, llm: Any, max_memories: int = 40,
) -> tuple[str, str] | None:
    """LLM picks the best memory matching `phrase` semantically.

    Returns (memory_text, date_str) or None. For event_interval, we
    don't extract age_at — just the date. The phrase match is harder
    than token overlap (e.g., "started sculpting classes" matching
    "I just started taking sculpting classes today").
    """
    if not llm or not memories:
        return None
    from radiomind.refinement.trinity import debate

    lines = []
    for m in memories[:max_memories]:
        if hasattr(m, "entry"):
            meta = m.entry.metadata or {}
            sdate = meta.get("event_date") or meta.get("session_date", "")
            content = m.entry.content or ""
        elif isinstance(m, dict):
            sdate = m.get("event_date") or m.get("created_at") or m.get("session_date", "")
            content = m.get("memory") or m.get("content") or ""
        else:
            continue
        if not sdate or not content:
            continue
        lines.append(f"[{sdate}] {content[:400].replace(chr(10), ' ')}")
    if not lines:
        return None
    evidence = "\n".join(lines)

    result = debate(
        task=(
            f"In these memories, find the single turn that best matches "
            f"this event phrase (semantic match, ignore minor wording "
            f"differences): '{phrase}'. Return the event_date in YYYY-MM-DD "
            f"and a short memory snippet.\n"
            f"Tensions: exact-phrase-match (require literal wording) vs "
            f"semantic-paraphrase (accept equivalents like 'started X' ≡ "
            f"'just began X') vs abstain-if-evidence-thin."
        ),
        evidence=evidence,
        llm=llm,
        extra_schema=(
            '  "event_date": str (YYYY-MM-DD or ""),\n'
            '  "event_memory": str (memory text snippet)'
        ),
    )
    if not result:
        return None
    date = str(result.get("event_date") or "").strip()
    if not date:
        return None
    mem = str(result.get("event_memory") or "").strip()[:200]
    return (mem, date)


def _find_event_in_store(
    mind, phrase: str, domain: str | None = None,
) -> tuple[str, str] | None:
    """Scan domain's full FACT layer for best phrase match with a date."""
    if mind is None or not getattr(mind, "_store", None):
        return None
    try:
        from radiomind.core.types import MemoryLevel
        facts = mind._store.list_by_domain(
            domain or "", level=MemoryLevel.FACT, limit=500,
        )
    except Exception:
        return None
    stop = {"the", "a", "an", "i", "my", "was", "were", "from", "to", "at",
            "on", "in", "of", "for", "with", "and", "or", "but"}
    tokens = [
        t for t in re.findall(r"[a-z0-9]+", (phrase or "").lower())
        if len(t) > 2 and t not in stop
    ]
    if not tokens:
        return None
    best: tuple[float, str, str] | None = None
    for entry in facts:
        content = entry.content or ""
        low = content.lower()
        score = sum(1 for t in tokens if t in low) / len(tokens)
        if score < 0.4:
            continue
        sdate = (entry.metadata or {}).get(
            "event_date") or (entry.metadata or {}).get("session_date", "")
        if not sdate:
            continue
        if best is None or score > best[0]:
            best = (score, content[:200], str(sdate))
    if best is None:
        return None
    return (best[1], best[2])


def _resolve_anchor(
    phrase: str, memories: list, mind, llm, domain: str | None,
) -> tuple[str, datetime] | None:
    """Three-tier: token → trinity → store. Returns (text, date) or None."""
    # Tier 1: token match with date
    matches = _find_event_mentions(phrase, memories)
    for content, date_str in matches:
        d = _parse_date(date_str)
        if d is not None:
            return (content, d)
    # Tier 2: trinity semantic match
    if llm is not None:
        esc = _find_event_via_trinity(phrase, memories, llm)
        if esc is not None:
            d = _parse_date(esc[1])
            if d is not None:
                return (esc[0], d)
    # Tier 3: full FACT scan
    scan = _find_event_in_store(mind, phrase, domain)
    if scan is not None:
        d = _parse_date(scan[1])
        if d is not None:
            return (scan[0], d)
    return None


def _trinity_validate(
    unit: str, interval_value: int,
    anchor_a: tuple[str, datetime],
    anchor_b: tuple[str, datetime],
    question: str,
    llm: Any,
) -> bool:
    """Three-stance commit/abstain/revise check on the computed interval."""
    from radiomind.refinement.trinity import debate

    evidence = (
        f"Anchor A (event A): {anchor_a[0]}  (date: {anchor_a[1].strftime('%Y-%m-%d')})\n"
        f"Anchor B (event B): {anchor_b[0]}  (date: {anchor_b[1].strftime('%Y-%m-%d')})\n"
        f"Computed interval: {interval_value} {unit}"
    )
    result = debate(
        task=(
            f"Decide whether to COMMIT, ABSTAIN, or REVISE this event-"
            f"interval computation. Triangulate: strict-anchor (both "
            f"anchors must clearly correspond to the two events in "
            f"the question, no distractors) vs inferential (paraphrase "
            f"anchors OK) vs time-sanity (does the interval make sense "
            f"for the two events).\n"
            f"Question: {question}"
        ),
        evidence=evidence,
        llm=llm,
        extra_schema='  "verdict": "commit"|"abstain"|"revise"',
    )
    if not result:
        return False
    v = str(result.get("verdict") or "").lower()
    return v == "commit"


class EventIntervalSkill(Skill):
    name = "event_interval"
    priority = 18  # after age_interval (15), before most others

    def match(self, signature: Any) -> bool:
        return True  # registry calls resolve(); trigger regex gates inside

    def resolve(self, query: str, memories: list, context: dict) -> SkillResult | None:
        if not _INTERVAL_UNIT_RE.search(query):
            return None

        # Decide which shape fired and extract (phrase_a, phrase_b, unit)
        unit: str
        phrase_a: str
        phrase_b: str
        m = _A_BEEN_WHEN_RE.search(query)
        if m:
            unit, phrase_a, phrase_b = m.group(1), m.group(2).strip(), m.group(3).strip()
        else:
            m = _BETWEEN_RE.search(query)
            if m:
                unit, phrase_a, phrase_b = m.group(1), m.group(2).strip(), m.group(3).strip()
            else:
                m = _SINCE_WHEN_RE.search(query)
                if m:
                    unit, phrase_a, phrase_b = m.group(1), m.group(2).strip(), m.group(3).strip()
                else:
                    return None

        mind = context.get("mind")
        llm = mind._llm if mind else None
        domain = context.get("domain") or ""

        # Guard against overlap with age_interval ("when I graduated")
        # — age_interval already handles age-related shapes. Here we
        # skip if either phrase mentions age explicitly.
        if re.search(r"\bage|\byears?\s+old\b|\bborn\b", phrase_a + " " + phrase_b, re.IGNORECASE):
            return None

        anchor_a = _resolve_anchor(phrase_a, memories, mind, llm, domain)
        if anchor_a is None:
            return None
        anchor_b = _resolve_anchor(phrase_b, memories, mind, llm, domain)
        if anchor_b is None:
            return None

        # Ordering: conventionally event A is earlier, B is later; but
        # question shape "when I Y-ed" implies B is the later event and
        # A is the ongoing/prior event. Interval = |b - a|.
        delta_days = abs((anchor_b[1] - anchor_a[1]).days)
        unit_days = _unit_to_days(unit)
        value = delta_days // unit_days if unit_days > 0 else delta_days
        if value <= 0 or value > 1200:  # sanity (> 3 years in days)
            return None

        if llm is not None:
            if not _trinity_validate(
                unit=unit, interval_value=value,
                anchor_a=anchor_a, anchor_b=anchor_b,
                question=query, llm=llm,
            ):
                return None

        return SkillResult(
            skill_name=self.name,
            answer=f"{value} {unit}",
            anchors=[
                (f"event A ({phrase_a})", anchor_a[1].strftime("%Y-%m-%d")),
                (f"event B ({phrase_b})", anchor_b[1].strftime("%Y-%m-%d")),
            ],
            confidence=0.85,
        )


from radiomind.skills.registry import register  # noqa: E402

register(EventIntervalSkill())
