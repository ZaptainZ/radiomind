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

import logging
import re
from datetime import datetime
from typing import Any

from radiomind.skills.base import Skill, SkillResult

_logger = logging.getLogger(__name__)


# Sentinel: trinity abstained (chose -1 OR retry-consistency failed).
# Distinguishes "trinity says none of these are the right anchor" from
# "trinity confidently picked one". Caller routes abstain → semantic
# search (_find_event_via_trinity) instead of falling back to
# candidates[0] (which was V6.1's only escape and equals V5's failure
# mode).
class _AbstainSentinel:
    __slots__ = ()
    def __repr__(self) -> str: return "<TRINITY_ABSTAIN>"

TRINITY_ABSTAIN: _AbstainSentinel = _AbstainSentinel()


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


_YMD_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    # Robust first pass: extract YYYY(-|/)M(-|/)D from anywhere in the
    # string. Handles LongMemEval's "2023/05/26 (Mon) 14:08" shape that
    # the strict strptime fallback was missing into mid-year stubs.
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


def _trinity_select_once(
    phrase: str, candidates: list[tuple[str, str]],
    query: str, llm: Any,
) -> int | None:
    """Single trinity LLM call. Returns chosen_index, -1 (abstain),
    or None on parse/LLM failure. No fallback — caller decides."""
    ev_lines = []
    for i, (content, date_str) in enumerate(candidates):
        snippet = (content or "")[:200].replace("\n", " ")
        ev_lines.append(f"candidate_idx={i} | date={date_str} | {snippet}")
    evidence = "\n".join(ev_lines)
    from radiomind.refinement import trinity as _trinity
    result = _trinity.fast(
        task=(
            f"Pick the BEST anchor candidate for this question's "
            f"event reference. Three independent dimensions:\n"
            f"  literal-match — does the candidate literally describe "
            f"the event the question references (event phrase: "
            f"{phrase!r})?\n"
            f"  semantic-paraphrase — does the candidate describe the "
            f"SAME event with different words (e.g. 'graduated college' "
            f"matches 'completed my Bachelor's degree')?\n"
            f"  temporal-context — does the candidate's date make "
            f"biographical sense given the question's framing? Pick "
            f"the candidate whose date is most plausibly the event the "
            f"user is asking about, NOT a third-party event "
            f"(niece's, friend's) the user only witnessed.\n"
            f"\n"
            f"Output `chosen_index` (0-based). If NONE of the candidates "
            f"is the user's own anchor event (all are third-party / "
            f"irrelevant), output -1 to abstain.\n"
            f"Question: {query}"
        ),
        evidence=evidence,
        llm=llm,
        extra_schema='  "chosen_index": int  (-1 for abstain)',
    )
    if not result:
        return None
    try:
        return int(result.get("chosen_index"))
    except (TypeError, ValueError):
        return None


def _trinity_select_anchor(
    phrase: str, candidates: list[tuple[str, str]],
    query: str, llm: Any,
) -> tuple[str, str] | _AbstainSentinel | None:
    """Trinity-3-party anchor selection with retry-consistency + abstain.

    GAP-D V6.1.1 hardening over V6.1:
      - Retry-with-consistency: 2 trinity calls; trust only when both
        return the same chosen_index. c18a7dc8 had ~60-80% V6.1 PASS
        rate; consistency check pushes to ≥85% by filtering single-
        call LLM noise.
      - Abstain (-1) option: trinity can declare "none of these is the
        user's own event"; caller routes to V5's _find_event_via_trinity
        (semantic search), not candidates[0]. Stops the V6.1 silent
        fallback to V5's failure mode on inconsistent / parse-failure.
      - All inconsistencies → abstain (conservative).

    Three stances (CORE_METHODOLOGY dimension-typed naming):
      literal-match       — does it literally describe the event?
      semantic-paraphrase — does it describe the SAME event differently?
      temporal-context    — does its date make biographical sense?

    Returns:
      tuple[str, str]      — (content, date_str) when consistent valid pick
      TRINITY_ABSTAIN      — trinity abstained or inconsistent picks
      None                 — no LLM or empty candidates
      candidates[0]        — single-candidate shortcut (untouched from V6.1)
    """
    if not llm or not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    idx1 = _trinity_select_once(phrase, candidates, query, llm)
    idx2 = _trinity_select_once(phrase, candidates, query, llm)

    decision = "abstain"
    picked: tuple[str, str] | _AbstainSentinel = TRINITY_ABSTAIN

    # Trust only when BOTH calls agree. Anything else → abstain
    # (let the caller fall back to semantic search).
    if idx1 is not None and idx1 == idx2:
        if idx1 == -1:
            decision = "abstain-explicit"
        elif 0 <= idx1 < len(candidates):
            decision = f"pick-{idx1}-consistent"
            picked = candidates[idx1]
        else:
            decision = "abstain-invalid-index"
    else:
        if idx1 is None and idx2 is None:
            decision = "abstain-both-parse-failed"
        elif idx1 != idx2:
            decision = f"abstain-inconsistent-{idx1}-vs-{idx2}"

    _logger.debug(
        "trinity_select_anchor: phrase=%r, n_candidates=%d, "
        "idx1=%s, idx2=%s, decision=%s",
        phrase, len(candidates), idx1, idx2, decision,
    )
    return picked


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
        # balanced (2 rounds): semantic event matching often picks the
        # wrong memory in round 1 when multiple events share keywords;
        # round 2 reconsiders given the prior pick and the others.
        max_rounds=2,
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
        # deep (3 rounds + depth-1 sub-trinity): this verdict directly
        # decides the user-facing answer for age-interval questions.
        # c18a7dc8-style failures (delta=0 vs gold=7) come from round 1
        # picking the wrong anchor without re-examining; multi-round
        # plus per-stance recursion pushes precision higher.
        max_rounds=3,
        sub_trinity_depth=1,
        converge_threshold=0.75,
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


def _find_age_at_event_in_store(
    mind, phrase: str, domain: str | None = None,
) -> tuple[str, str, int] | None:
    """Fallback: when neither token-match nor trinity over the top-N
    retrieved memories can locate the anchor event (happens on long
    haystacks where the 'at the age of 25' turn gets pushed out of
    top-k by unrelated chatter), scan the whole domain's FACT layer
    for any turn containing both a phrase-overlap hint AND an explicit
    age-at-event marker ('at the age of N' / 'when I was N' / 'aged N').

    Returns (memory_text, date_str, age) or None.
    """
    if mind is None or not getattr(mind, "_store", None):
        return None
    try:
        from radiomind.core.types import MemoryLevel
        facts = mind._store.list_by_domain(
            domain or "", level=MemoryLevel.FACT, limit=500,
        )
    except Exception:
        return None
    stop = {"the", "a", "an", "i", "my", "was", "were", "from", "to", "at"}
    tokens = [
        t for t in re.findall(r"[a-z0-9]+", (phrase or "").lower())
        if len(t) > 2 and t not in stop
    ]
    # Locate the actual "at the age of N" sentence so downstream
    # validators (trinity_validate) see the critical phrase — not a
    # random first-200-chars slice that may have chopped it off.
    _AGE_SENT_RE = re.compile(
        r"[^.!?]*(?:at\s+the\s+age\s+of|when\s+I\s+was|aged)\s+\d{1,3}[^.!?]*[.!?]?",
        re.IGNORECASE,
    )
    best: tuple[float, str, str, int] | None = None
    for entry in facts:
        content = entry.content or ""
        age = _age_at_event(content)
        if age is None:
            continue
        low = content.lower()
        score = (
            sum(1 for t in tokens if t in low) / len(tokens)
            if tokens else 0.0
        )
        # Even 0-overlap entries are candidates here (phrase may be a
        # pure paraphrase), but score ties favor literal overlap.
        sdate = (entry.metadata or {}).get(
            "event_date") or (entry.metadata or {}).get("session_date", "")
        if not sdate:
            continue
        # Extract the sentence around the age marker. If regex misses,
        # fall back to a window centered on the match.
        snippet = ""
        sent_m = _AGE_SENT_RE.search(content)
        if sent_m:
            snippet = sent_m.group(0).strip()[:400]
        else:
            # Center 200-char window around the age phrase
            age_m = re.search(
                r"(?:at\s+the\s+age\s+of|when\s+I\s+was|aged)\s+\d{1,3}",
                content, re.IGNORECASE,
            )
            if age_m:
                start = max(0, age_m.start() - 80)
                end = min(len(content), age_m.end() + 120)
                snippet = content[start:end].strip()
            else:
                snippet = content[:300]
        if best is None or score > best[0]:
            best = (score, snippet, str(sdate), age)
    if best is None:
        return None
    return (best[1], best[2], best[3])


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

        # Anchor B: event mentioned in memories.
        #
        # Token-match alone is fragile on this shape of question:
        # "graduated from college" → tokens {graduated, college} also match
        # "my niece who just graduated from high school" (half overlap),
        # which wins before the real "completed Bachelor's" memory. The
        # false match then silently blocks trinity escalation.
        #
        # Strategy (in order):
        #   1. Among token-matches, prefer one with extractable age_at_event.
        #   2. In older/younger mode (where age_at_event is critical),
        #      always run trinity escalation even if token-match found
        #      something — the semantic match is much better at ignoring
        #      distractors (niece, friend, parent graduations).
        #   3. Fall back to the first token-match (date-only) if both fail.
        b_matches = _find_event_mentions(phrase_b, memories)
        b_content = b_date_str = None
        b_age_at = None

        # (1) Prefer a token-match that already carries age_at_event info.
        for content, date_str in b_matches:
            age = _age_at_event(content)
            if age is not None:
                b_content, b_date_str, b_age_at = content, date_str, age
                break

        # (2) Escalate to trinity in older/younger mode for better semantics.
        if b_content is None and mode in ("older", "younger") and llm is not None:
            esc = _find_event_via_trinity(phrase_b, memories, llm)
            if esc is not None:
                b_content, b_date_str, b_age_at = esc

        # (2b) Store-scan for "at the age of N" anywhere in the domain.
        # Long haystacks push the critical turn out of top-k retrieval.
        # This catches that case symmetrically to the current-age store-scan.
        if b_content is None and mode in ("older", "younger"):
            domain_name = context.get("domain")
            scan = _find_age_at_event_in_store(mind, phrase_b, domain_name)
            if scan is not None:
                b_content, b_date_str, b_age_at = scan

        # (3) GAP-D + V6.1.1: trinity-driven anchor selection with
        # retry-consistency + abstain. V6.1 always picked something
        # (candidates[0] or trinity's first guess); V6.1.1 abstains
        # on inconsistency and routes to the semantic-search escape
        # (_find_event_via_trinity, V5 path) — strictly safer than
        # silently picking the wrong third-party event.
        if b_content is None:
            if len(b_matches) >= 2 and llm is not None:
                picked = _trinity_select_anchor(phrase_b, b_matches, query, llm)
                if picked is TRINITY_ABSTAIN:
                    # Trinity inconsistent or explicit abstain — try
                    # semantic search before falling back to candidates[0].
                    esc = _find_event_via_trinity(phrase_b, memories, llm)
                    if esc is not None:
                        b_content, b_date_str, b_age_at = esc
                    else:
                        b_content, b_date_str = b_matches[0]
                elif picked is not None:
                    b_content, b_date_str = picked
                else:
                    # Defensive: shouldn't happen since llm is not None
                    # and candidates non-empty, but cover for safety.
                    b_content, b_date_str = b_matches[0]
            elif b_matches:
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
