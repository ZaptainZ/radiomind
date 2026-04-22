"""Age / interval arithmetic — compute year gaps between life-events.

Handles "how many years older am I than when I Xed?" and siblings:
  - "how many years since I graduated"
  - "years between my move and my wedding"

Extracts date anchors from retrieved memories, computes the interval,
then validates with a mini-trinity debate (3 opposing stances) before
committing. Skill abstains when the evidence doesn't clearly locate
both anchors — wrong answer hurts more than no answer.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from radiomind.skills.base import Skill, SkillResult


# Trigger patterns — "how many years {older|younger|since|between}"
_TRIGGER_RE = re.compile(
    r"how\s+many\s+(?:years?|months?)\s+"
    r"(older|younger|since|between|after|before|apart)",
    re.IGNORECASE,
)

# "How many years older am I than when I graduated" — second anchor phrase
_WHEN_I_RE = re.compile(
    r"when\s+i\s+(.+?)(?:\?|$|\.)", re.IGNORECASE,
)
# "since I graduated from college"
_SINCE_I_RE = re.compile(
    r"since\s+i\s+(.+?)(?:\?|$|\.)", re.IGNORECASE,
)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y")


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s[: len(fmt) + 4], fmt)
        except ValueError:
            continue
    m = _YEAR_RE.search(s)
    if m:
        try:
            return datetime(int(m.group(0)), 6, 15)  # mid-year if only year known
        except ValueError:
            return None
    return None


def _find_event_mentions(
    phrase: str, memories: list, limit: int = 6,
) -> list[tuple[str, str]]:
    """Return [(memory_text, date_str)] for memories matching the phrase."""
    stop = {"the", "a", "an", "i", "my", "was", "were", "from", "to", "at"}
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
        if score >= 0.4:
            hits.append((score, content[:160], str(sdate)))
    hits.sort(key=lambda x: -x[0])
    return [(c, d) for _, c, d in hits[:limit]]


def _find_event_via_trinity(
    phrase: str, memories: list, llm: Any, max_memories: int = 30,
) -> tuple[str, str, int | None] | None:
    """Escalation: use trinity to find the event semantically.

    When token-overlap fails (e.g. "graduated from college" ≠ "completed
    Bachelor's at age 25"), we ask the LLM to locate the best-matching
    memory and extract its date + age-at-event. Three opposing stances
    (literal-mention / semantic-paraphrase / abstain-if-evidence-thin).
    Returns (memory_text, date, age_at_event_or_none) or None.
    """
    if not llm or not memories:
        return None
    from radiomind.refinement.trinity import debate

    mem_lines = []
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
        mem_lines.append(f"[{sdate}] {content[:400].replace(chr(10), ' ')}")
    if not mem_lines:
        return None
    evidence = "\n".join(mem_lines)

    result = debate(
        task=(
            f"In these memories, find when the user did the following event "
            f"(match on meaning, not just literal wording): '{phrase}'. "
            f"For example, 'graduated from college' matches 'completed a "
            f"Bachelor's degree'. Extract also the user's age-at-event if "
            f"the memory states it explicitly (e.g. 'at the age of 25').\n"
            f"Tensions: literal-mention (require exact phrasing) vs "
            f"semantic-paraphrase (accept equivalent meanings) vs "
            f"abstain-if-evidence-thin."
        ),
        evidence=evidence,
        llm=llm,
        extra_schema=(
            '  "event_date": str (YYYY-MM-DD or ""),\n'
            '  "event_memory": str (memory text snippet),\n'
            '  "age_at_event": int | null'
        ),
    )
    if not result:
        return None
    date = str(result.get("event_date") or "").strip()
    if not date:
        return None
    mem_text = str(result.get("event_memory") or "").strip()
    age_at = result.get("age_at_event")
    try:
        age_at = int(age_at) if age_at is not None else None
    except (TypeError, ValueError):
        age_at = None
    return (mem_text[:200], date, age_at)


def _trinity_validate(
    candidate_answer: str,
    anchor_a: tuple[str, str],
    anchor_b: tuple[str, str],
    question: str,
    llm: Any,
) -> bool:
    """Three opposing stances on whether to commit the candidate answer."""
    from radiomind.refinement.trinity import debate

    evidence = (
        f"Anchor A: {anchor_a[0]}  (date: {anchor_a[1]})\n"
        f"Anchor B: {anchor_b[0]}  (date: {anchor_b[1]})\n"
        f"Candidate computed answer: {candidate_answer}"
    )
    result = debate(
        task=(
            f"Decide whether to COMMIT, ABSTAIN, or REVISE this age-interval "
            f"computation. Tensions to triangulate: strict-anchor (both "
            f"anchors must name the EXACT events in the question, otherwise "
            f"revise/abstain) vs inferential (anchors plausibly map even "
            f"with slight phrasing mismatch) vs time-sanity (does the "
            f"computed interval make biological/life-stage sense).\n"
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


def _profile_age_info(mind) -> dict:
    """Extract current_age / birth_year from user profile (who section)."""
    if mind is None or not getattr(mind, "_meta", None):
        return {}
    profile = getattr(mind._meta, "user", None)
    if not profile or not isinstance(profile.who, dict):
        return {}
    info: dict = {}
    # Common keys: age, birth_year, year_of_birth
    for k in ("age", "current_age"):
        v = profile.who.get(k)
        if v:
            m = re.search(r"\d+", str(v))
            if m:
                info["age"] = int(m.group(0))
                break
    for k in ("birth_year", "year_of_birth", "born"):
        v = profile.who.get(k)
        if v:
            m = re.search(r"(19|20)\d{2}", str(v))
            if m:
                info["birth_year"] = int(m.group(0))
                break
    return info


def _age_at_event(mention: str) -> int | None:
    """Try to pull 'at the age of N' / 'when I was N' from a memory snippet."""
    m = re.search(
        r"(?:at\s+the\s+age\s+of|when\s+I\s+was|aged)\s+(\d{1,3})",
        mention, re.IGNORECASE,
    )
    return int(m.group(1)) if m else None


_CURRENT_AGE_PATTERNS = [
    re.compile(r"\bi(?:'m|\s+am)\s+(?:a\s+)?(\d{2})(?:[\s,\.\!\?]|\s+year)", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+(\d{2})[-\s]year[-\s]old\b", re.IGNORECASE),
    re.compile(
        r"\b(\d{2})[-\s]year[-\s]old\s+"
        r"(?:digital|marketing|software|designer|engineer|student|consultant|professional|specialist|man|woman|guy|girl|boy|programmer|developer|analyst)",
        re.IGNORECASE,
    ),
]


def _scan_for_current_age(text: str) -> int | None:
    for pat in _CURRENT_AGE_PATTERNS:
        mm = pat.search(text)
        if mm:
            age = int(mm.group(1))
            if 10 <= age <= 110:
                return age
    return None


def _find_current_age_in_memories(memories: list) -> int | None:
    """Scan retrieved memories for user's CURRENT age (self-id only).

    DOES NOT include past-event age mentions ("at the age of 25 I graduated").
    """
    for m in memories[:80]:
        if hasattr(m, "entry"):
            content = m.entry.content or ""
        elif isinstance(m, dict):
            content = m.get("memory") or m.get("content") or ""
        else:
            continue
        age = _scan_for_current_age(content)
        if age is not None:
            return age
    return None


def _find_current_age_in_store(mind, domain: str | None = None) -> int | None:
    """Fallback: retrieval may miss the self-ID turn (e.g. 'as a 32-year-old
    Digital Marketing Specialist' has no token overlap with a 'graduation'
    query). Scan the domain's full fact store for self-id patterns.
    """
    if mind is None or not getattr(mind, "_store", None):
        return None
    try:
        # Cap to 500 to keep the scan bounded on huge stores
        from radiomind.core.types import MemoryLevel
        facts = mind._store.list_by_domain(
            domain or "", level=MemoryLevel.FACT, limit=500,
        )
    except Exception:
        return None
    for entry in facts:
        age = _scan_for_current_age(entry.content or "")
        if age is not None:
            return age
    return None


class AgeIntervalSkill(Skill):
    name = "age_interval"
    priority = 15

    def match(self, signature: Any) -> bool:
        return True  # registry will call resolve(); signature is loose

    def resolve(self, query: str, memories: list, context: dict) -> SkillResult | None:
        m = _TRIGGER_RE.search(query)
        if not m:
            return None
        mode = m.group(1).lower()  # older/younger/since/between/...
        mind = context.get("mind")
        llm = mind._llm if mind else None

        phrase_b: str | None = None
        wm = _WHEN_I_RE.search(query)
        sm = _SINCE_I_RE.search(query)
        if wm:
            phrase_b = wm.group(1).strip().rstrip("?.!")
        elif sm:
            phrase_b = sm.group(1).strip().rstrip("?.!")
        if not phrase_b:
            return None

        # Anchor B: event mentioned in memories. Try fast token-match first;
        # escalate to trinity-based semantic match if that fails (e.g.
        # "graduated from college" ↔ "completed Bachelor's at age 25").
        b_matches = _find_event_mentions(phrase_b, memories)
        b_age_at = None
        if b_matches:
            b_content, b_date_str = b_matches[0]
        elif llm is not None:
            esc = _find_event_via_trinity(phrase_b, memories, llm)
            if esc is None:
                return None
            b_content, b_date_str, b_age_at = esc
        else:
            return None
        b_date = _parse_date(b_date_str)

        # Combine sources for current age / current year
        ref_str = context.get("reference_date") or ""
        a_date = _parse_date(ref_str) or datetime.now()
        profile_info = _profile_age_info(mind)

        candidate: str | None = None
        anchor_a_label = "today / ref date"
        anchor_a_value = a_date.strftime("%Y-%m-%d")

        # Path 1: memory says "at the age of N" and we know current age M
        # → answer = M - N. Current age sourced (in order):
        #   1. user profile (who.age or birth_year → derive)
        #   2. direct scan of memories for self-id ("I'm 32" / "as a 32-year-old")
        # age_at_event comes from (in order): trinity-escalation pick,
        # regex scan on the anchor memory content.
        age_at_event = b_age_at if b_age_at is not None else _age_at_event(b_content)
        if mode in ("older", "younger") and age_at_event is not None:
            current_age = profile_info.get("age")
            source = "profile"
            if current_age is None and profile_info.get("birth_year"):
                current_age = a_date.year - int(profile_info["birth_year"])
                source = "profile birth_year"
            if current_age is None:
                # Fallback 1: scan retrieved memories for self-ID pattern
                current_age = _find_current_age_in_memories(memories)
                source = "retrieved self-ID"
            if current_age is None:
                # Fallback 2: scan the full domain store. Self-ID turns
                # often don't get retrieved (no token overlap with the
                # question), but they do sit in the L0 FACT layer.
                domain_name = context.get("domain")
                current_age = _find_current_age_in_store(mind, domain_name)
                source = "store self-ID"
            if current_age is not None:
                years = current_age - age_at_event
                if 0 <= years <= 120:
                    candidate = str(years)
                    anchor_a_label = f"current age ({source})"
                    anchor_a_value = str(current_age)

        # Path 2: fallback — use event date vs ref date subtraction
        if candidate is None and b_date is not None:
            delta_days = (a_date - b_date).days
            if mode in ("since", "older"):
                years = delta_days // 365
            elif mode == "younger":
                years = -(delta_days // 365)
            else:
                years = abs(delta_days) // 365
            if 0 <= years <= 120:
                candidate = str(years)

        if candidate is None:
            return None

        # Trinity validation
        if llm is not None:
            if not _trinity_validate(
                candidate_answer=candidate,
                anchor_a=(anchor_a_label, anchor_a_value),
                anchor_b=(b_content, b_date.strftime("%Y-%m-%d") if b_date else b_date_str),
                question=query,
                llm=llm,
            ):
                return None

        return SkillResult(
            skill_name=self.name,
            answer=candidate,
            anchors=[
                (phrase_b, b_date.strftime("%Y-%m-%d") if b_date else b_date_str),
                (anchor_a_label, anchor_a_value),
            ],
            confidence=0.9,
        )


from radiomind.skills.registry import register  # noqa: E402

register(AgeIntervalSkill())
