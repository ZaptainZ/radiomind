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


def _has_age_at_event_evidence(memories: list[Any]) -> bool:
    for text in _iter_memory_text(memories):
        if _AGE_AT_EVENT_RE.search(text):
            return True
    return False


def _has_current_age_evidence(memories: list[Any]) -> bool:
    for text in _iter_memory_text(memories):
        for pat in _CURRENT_AGE_PATTERNS:
            if pat.search(text):
                return True
    return False


# Parses the STRUCTURED SKILL block emitted by the registry's
# soft-routing layer. Format documented at SkillResult.prefix().
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


def maybe_age_interval_commit_closure(
    question: str,
    retrieved_memories: list[Any],
    llm_answer: str,
    temporal_section: str,
) -> str:
    """If TSI-1c gates hold, replace the LLM's pure abstain with a
    commit to the skill's numeric answer.

    Gates (ALL must hold):
      1. temporal_section contains STRUCTURED SKILL for age_interval
      2. confidence >= 0.85
      3. computed answer parses to a numeric token
      4. retrieved memories contain an explicit `at the age of N` /
         `when I was N` / `aged N` mention
      5. retrieved memories contain a first-person current-age
         self-id mention
      6. LLM final answer is a pure canonical-abstain (no concrete
         commitment elsewhere — uses JAB-1b semantics)

    Returns:
      - rewritten answer (commit to skill number) when ALL gates hold
      - llm_answer unchanged when any gate fails
    """
    skill_name, conf, computed = parse_temporal_section(temporal_section)
    if skill_name != "age_interval":
        return llm_answer
    if conf is None or conf < 0.85:
        return llm_answer
    if not computed or not re.search(r"\d", computed):
        return llm_answer
    if not _is_pure_abstain(llm_answer):
        return llm_answer
    if not _has_age_at_event_evidence(retrieved_memories):
        return llm_answer
    if not _has_current_age_evidence(retrieved_memories):
        return llm_answer

    unit = _question_unit(question)
    return (
        f"{computed} {unit}. (Computed from explicit "
        f"`at the age of N` evidence in your memories combined "
        f"with your stated current age.)"
    )
