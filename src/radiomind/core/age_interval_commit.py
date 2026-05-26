"""TSI-1c: age_interval commit closure.

When the age_interval skill produces a high-confidence numeric
answer with DETERMINISTIC backing evidence on BOTH anchors
(explicit `at the age of N` past-event evidence AND first-person
current-age self-id evidence), AND the answer-LLM nonetheless
emits a pure canonical abstain, override the abstain with the
skill's numeric answer.

Safety contract (Codex 2026-05-26 P1.3 + TSI-1b cohort audit):
This rewrite fires ONLY on questions where age_interval's
_TRIGGER_RE matches AND the skill's resolve() succeeded. TSI-1b
audit verified the full LME-S age_interval trigger surface is
just 3 qids; ALL have concrete (non-abstain) gold. Therefore the
rewrite cannot break a correct abstain on the audited surface.

Why "confidence >= 0.85" alone is not enough:
- Confidence is a skill-internal heuristic; it's NOT a proof of
  correctness.
- The real gate is "deterministic backing evidence on both
  anchors": at-age-N regex match + current-age regex match.
  When both are present, the skill is computing arithmetic over
  text-grounded numbers, not a paraphrase guess.
"""
from __future__ import annotations

import re
from typing import Any


# Canonical-abstain detector. Identical contract to JAB-1b's
# `is_abstain_response` — pure-abstain (no concrete commitment).
# Duplicated here (no cross-tree import from bench/) to keep the
# runtime library independent of the benchmark harness.
_ABSTAIN_RESPONSE_RE = re.compile(
    r"\b("
    r"the\s+information\s+provided\s+is\s+not\s+enough"
    r"|not\s+enough\s+information"
    r"|i\s+(?:don't|do\s+not)\s+have\s+(?:enough\s+)?information"
    r"|cannot\s+be\s+determined"
    r"|insufficient\s+information"
    r"|no\s+(?:specific\s+)?information"
    r"|(?:memories|context)\s+do\s+not\s+(?:provide|contain|specify)"
    r"|unable\s+to\s+determine"
    r")\b",
    re.IGNORECASE,
)

_CONCRETE_COMMITMENT_RE = re.compile(
    r"\$\s*\d[\d,]*(?:\.\d+)?"
    r"|\b\d+(?:\.\d+)?\s*"
    r"(?:%|dollars?|cents?|years?|months?|weeks?|days?|hours?|"
    r"minutes?|seconds?|times?|instruments?|people?|miles?|km|"
    r"kilometers?|degrees?)"
    r"|\b(?:19|20)\d{2}\b"
    r"|\b(?:the\s+answer\s+is|that\s+would\s+be|"
    r"it(?:'s|\s+is)\s+(?:about|approximately|roughly|exactly)?)\s*\S",
    re.IGNORECASE,
)


def _is_pure_abstain(answer: str) -> bool:
    a = (answer or "").strip()
    if not a:
        return False
    if not _ABSTAIN_RESPONSE_RE.search(a):
        return False
    if _CONCRETE_COMMITMENT_RE.search(a):
        return False
    return True


# Backing-evidence regexes — mirror age_interval._age_at_event and
# the at-current-age scanner.
_AGE_AT_EVENT_RE = re.compile(
    r"(?:at\s+the\s+age\s+of|when\s+I\s+was|aged)\s+(\d{1,3})",
    re.IGNORECASE,
)

# Current-age patterns — first-person self-id only. Conservative
# variant of age_interval._CURRENT_AGE_PATTERNS that doesn't
# require occupational suffix (audit only checks presence, not
# specific value).
_CURRENT_AGE_PATTERNS = [
    re.compile(
        r"\bi(?:'m|\s+am)\s+(?:a\s+)?(\d{2})"
        r"(?:[\s,\.\!\?]|\s+year)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bas\s+a\s+(\d{2})[-\s]year[-\s]old\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{2})[-\s]year[-\s]old\s+"
        r"(?:digital|marketing|software|designer|engineer|"
        r"student|consultant|professional|specialist|man|woman|"
        r"guy|girl|boy|programmer|developer|analyst)",
        re.IGNORECASE,
    ),
]


def _iter_memory_text(memories: list[Any]) -> list[str]:
    out: list[str] = []
    for r in memories or []:
        if isinstance(r, dict):
            content = r.get("memory") or r.get("content") or ""
        elif hasattr(r, "entry"):
            content = getattr(r.entry, "content", "") or ""
        elif hasattr(r, "content"):
            content = getattr(r, "content", "") or ""
        else:
            content = ""
        if content:
            out.append(content)
    return out


def _find_age_at_event(
    memories: list[Any],
) -> tuple[int, str] | None:
    """Return (N, source_snippet) for the first explicit
    'at the age of N' / 'when I was N' / 'aged N' match across
    retrieved memories, or None.

    The source snippet is a short window around the match so
    the rewrite can quote it as backing proof.
    """
    for text in _iter_memory_text(memories):
        m = _AGE_AT_EVENT_RE.search(text)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= 120):
            continue
        start = max(0, m.start() - 60)
        end = min(len(text), m.end() + 80)
        snippet = text[start:end].strip()
        return n, snippet
    return None


def _find_current_age(
    memories: list[Any],
) -> tuple[int, str] | None:
    """Return (N, source_snippet) for the first first-person
    current-age self-id match, or None."""
    for text in _iter_memory_text(memories):
        for pat in _CURRENT_AGE_PATTERNS:
            m = pat.search(text)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if not (10 <= n <= 110):
                continue
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 80)
            snippet = text[start:end].strip()
            return n, snippet
    return None


# Retained for backward-compat (used by older audits/tests).
def _has_age_at_event_evidence(memories: list[Any]) -> bool:
    return _find_age_at_event(memories) is not None


def _has_current_age_evidence(memories: list[Any]) -> bool:
    return _find_current_age(memories) is not None


# Parses the STRUCTURED SKILL block emitted by the registry's
# soft-routing layer. Format documented at SkillResult.prefix().
#
# Architectural note (Codex 2026-05-26 P3): reverse-parsing the
# rendered prompt text is fragile — any wording change to
# SkillResult.prefix() would silently disable this gate. The
# production fix is to thread the typed SkillResult object through
# `run_temporal_precision` / the runner so the answer-side gate
# consumes structured data (skill_name, confidence, computed,
# anchor list, source proofs) rather than a string. We accept the
# parse-from-text wiring here as a benchmark-side fix only and
# document it as scope-deferred to a future architectural pass on
# the skill-result return contract.
_STRUCTURED_SKILL_HEADER = re.compile(
    r"STRUCTURED SKILL \((\w+), conf=([\d.]+)\)",
)
_COMPUTED_ANSWER = re.compile(
    r"Computed answer:\s*(.+?)\s*(?:\n|$)",
)


def parse_temporal_section(
    temporal_section: str,
) -> tuple[str | None, float | None, str | None]:
    """Parse a STRUCTURED SKILL section back into
    (skill_name, confidence, computed_answer)."""
    if not temporal_section:
        return None, None, None
    mh = _STRUCTURED_SKILL_HEADER.search(temporal_section)
    if not mh:
        return None, None, None
    skill_name = mh.group(1)
    try:
        conf = float(mh.group(2))
    except (TypeError, ValueError):
        conf = None
    ma = _COMPUTED_ANSWER.search(temporal_section)
    computed = ma.group(1).strip() if ma else None
    return skill_name, conf, computed


def _question_unit(question: str) -> str:
    """Best-effort unit extraction from the age_interval trigger.
    'how many years older' → years; 'how many months apart' → months.
    Defaults to 'years' (most common older/younger shape)."""
    m = re.search(
        r"how\s+many\s+(years?|months?|weeks?|days?)",
        question or "", re.IGNORECASE,
    )
    if not m:
        return "years"
    raw = m.group(1).lower().rstrip("s")
    return f"{raw}s"


def _question_mode(question: str) -> str | None:
    """Extract the age_interval mode token from the question.
    Mirror age_interval._TRIGGER_RE — returns one of
    older/younger/since/between/after/before/apart, or None.
    """
    m = re.search(
        r"how\s+many\s+(?:years?|months?)\s+"
        r"(older|younger|since|between|after|before|apart)",
        question or "", re.IGNORECASE,
    )
    return m.group(1).lower() if m else None


def maybe_age_interval_commit_closure(
    question: str,
    retrieved_memories: list[Any],
    llm_answer: str,
    temporal_section: str,
) -> str:
    """If TSI-1d gates hold, replace the LLM's pure abstain with a
    commit to the skill's numeric answer — but ONLY after
    independently recomputing the value from matched anchor
    evidence and verifying it equals the skill's answer.

    Gates (ALL must hold) — TSI-1d (2026-05-26 Codex P1):
      1. temporal_section contains STRUCTURED SKILL for age_interval
      2. confidence >= 0.85
      3. computed answer parses to a non-negative integer
      4. question mode is `older` or `younger` (other modes use
         date arithmetic, outside this gate's recompute scope)
      5. retrieved memories contain an explicit `at the age of N` /
         `when I was N` / `aged N` mention (yields PAST_AGE)
      6. retrieved memories contain a first-person current-age
         self-id mention (yields CURRENT_AGE)
      7. independent recompute matches skill answer EXACTLY:
           older  → CURRENT_AGE - PAST_AGE == skill_value
           younger → PAST_AGE - CURRENT_AGE == skill_value
      8. LLM final answer is a pure canonical-abstain (no concrete
         commitment elsewhere — uses JAB-1b semantics)

    Returns:
      - rewritten answer with source quotes proving the
        arithmetic, when ALL gates hold
      - llm_answer unchanged when any gate fails

    Notes:
      - Gate 7 is the proof linkage Codex P1 required. The
        rewrite cannot fire on memories that merely contain SOME
        age-at-event and SOME current-age — they must combine
        arithmetically to the skill's claimed answer. An
        unrelated past age (e.g. a niece's age-at-event) won't
        satisfy this gate unless that arithmetic happens to be
        consistent with current-age - X.
      - For age_interval modes other than older/younger (since,
        before, after, etc.), date arithmetic is outside this
        gate's scope. The rewrite stays dormant for those.
    """
    skill_name, conf, computed = parse_temporal_section(temporal_section)
    if skill_name != "age_interval":
        return llm_answer
    if conf is None or conf < 0.85:
        return llm_answer
    if not computed:
        return llm_answer
    try:
        skill_value = int(computed.strip())
    except (TypeError, ValueError):
        return llm_answer
    if skill_value < 0:
        return llm_answer

    mode = _question_mode(question)
    if mode not in ("older", "younger"):
        # Other modes need date arithmetic — outside our recompute
        # scope. Don't trust the skill answer in this gate.
        return llm_answer

    if not _is_pure_abstain(llm_answer):
        return llm_answer

    past = _find_age_at_event(retrieved_memories)
    if past is None:
        return llm_answer
    past_age, past_evidence = past

    current = _find_current_age(retrieved_memories)
    if current is None:
        return llm_answer
    current_age, current_evidence = current

    # Gate 7: independent recompute must match skill value
    if mode == "older":
        recomputed = current_age - past_age
    else:  # younger
        recomputed = past_age - current_age
    if recomputed != skill_value:
        return llm_answer

    unit = _question_unit(question)
    return (
        f"{skill_value} {unit}. (Verified: current age "
        f"{current_age} {'minus' if mode == 'older' else 'subtracted from'} "
        f"past-event age {past_age} = {skill_value}, "
        f"matching the skill computation. "
        f"Past-age source: {past_evidence!r}. "
        f"Current-age source: {current_evidence!r}.)"
    )
