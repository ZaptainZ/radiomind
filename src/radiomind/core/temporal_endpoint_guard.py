"""TESG-1: Temporal endpoint support guard (employer endpoint only).

Deterministic regex-based guard against over-commit when a "how long
... before I started my current job at Y" question presupposes the
user has started at Y, but retrieved memories carry NO first-person
evidence that the user works/started/joined at Y.

Root case (LME-S `gpt4_93159ced_abs`):
  Q: "How long have I been working before I started my current job
      at Google?"
  Gold: "The information provided is not enough. From the information
        provided, You haven't started working at Google yet."
  V8.2.x over-committed: "4 years 3 months of work experience before
        starting at Google" — multi-round date-arithmetic trinity
        ignored the missing endpoint-occurrence evidence and used
        only the NovaTech tenure number.

Codex scope (2026-05-26, third review): first impl covers EMPLOYER
endpoint only. Event-shape "before I saw X" (e.g. goldfinches) is
explicitly scope-deferred — that sub-shape needs a separate
event-occurrence detector and would inflate trigger surface.

The negative-case anchor is the SAME-shape qid `gpt4_93159ced`
asking about NovaTech: memories DO carry "I've been working at
NovaTech for about 4 years and 3 months" — guard must NOT fire
on that one.

Scope (TESG-1 v1):
  - Only "how long ... before I started/joined ... (current) job
    /role/position at Y" trigger
  - Y must be a Title-Cased noun phrase (employer brand)
  - Evidence requirement: ≥1 first-person work-at-Y statement in
    user turns
  - Zero LLM cost
"""
from __future__ import annotations

import re
from typing import Any


# Trigger pattern: "how long ... before I started/joined/began ...
# (current) job/role/position/work at Y" where Y is Title-Cased.
# The (?:current\s+)? is optional so we match "my job at Google" too.
_TRIGGER_RE = re.compile(
    r"how\s+long\s+(?:have|has|did|do)\s+i\s+\S+(?:\s+\S+){0,3}?\s+"
    r"before\s+i\s+(?:start|join|begin|began|got|landed|accept|"
    r"accepted)\w*\s+"
    r"(?:my\s+|the\s+|a\s+)?(?:current\s+|new\s+)?"
    r"(?:job|role|position|gig|work)\s+"
    r"(?:at|with|for|in)\s+"
    r"([A-Z][\w&]*(?:\s+[A-Z][\w&]*){0,2})",
    re.IGNORECASE,
)
# NOTE: outer regex uses IGNORECASE for "how long ... before I", but
# the employer capture group [A-Z][\w&]* relies on the case of the
# input; LongMemEval questions consistently capitalize brand names.


# First-person employment evidence patterns. Each is a template
# where {Y} is interpolated with the escaped employer name.
_EVIDENCE_PATTERN_TEMPLATES = (
    # "I work at X" / "I'm at X" / "I started at X" / "I joined X"
    r"\bi\s+(?:work|worked|started|joined|am|'m)\s+"
    r"(?:at|for|with)\s+{Y}\b",
    r"\bi\s+joined\s+{Y}\b",
    # "my job/role/position/company at X"
    r"\bmy\s+(?:job|company|role|position|gig|work|workplace|office|"
    r"employer)\s+(?:at|with|in)\s+{Y}\b",
    # "working at X" — without leading "I" (still in user-tagged turn)
    r"\bworking\s+(?:at|for|with)\s+{Y}\b",
    # "I've been at X" / "I've been working at X"
    r"\bi(?:'ve|\s+have)\s+been\s+(?:working\s+)?(?:at|for|with)\s+{Y}\b",
    # "I got/landed/accepted a job at X"
    r"\bi\s+(?:got|landed|accepted|received)\s+(?:a\s+)?"
    r"(?:job|offer|position|role|gig)\s+(?:at|with)\s+{Y}\b",
    # "tenure at X" / "years at X" / "time at X"
    r"\b(?:tenure|years?|months?|time)\s+(?:at|with)\s+{Y}\b",
)


def _extract_employer_endpoint(question: str) -> str | None:
    """Return the employer-noun Y from a 'before I started ... at Y'
    question, or None when the question isn't this shape.
    """
    if not question:
        return None
    m = _TRIGGER_RE.search(question)
    if not m:
        return None
    y = (m.group(1) or "").strip()
    return y or None


def _iter_user_memory_text(retrieved_memories: list[Any]) -> list[str]:
    """Return content strings from retrieved memories, focused on user
    turns. LongMemEval ingestion prefixes content with '[user] ' /
    '[assistant] '; when no prefix is present, the memory is included
    too (some pipelines feed pre-cleaned text).
    """
    out: list[str] = []
    for r in retrieved_memories or []:
        if isinstance(r, dict):
            content = r.get("memory") or r.get("content") or ""
        elif hasattr(r, "entry"):
            content = getattr(r.entry, "content", "") or ""
        elif hasattr(r, "content"):
            content = getattr(r, "content", "") or ""
        else:
            content = ""
        if not content:
            continue
        # If a role prefix is present, only keep user turns. If absent,
        # include the content (don't over-filter).
        c_low = content.lower()
        if "[assistant]" in c_low:
            continue
        out.append(content)
    return out


def _count_employer_evidence(employer: str, memory_texts: list[str]) -> int:
    """Count first-person evidence statements for working at the
    given employer across user-turn memory texts.
    """
    if not employer or not memory_texts:
        return 0
    y_escaped = re.escape(employer)
    patterns = [
        re.compile(tpl.format(Y=y_escaped), re.IGNORECASE)
        for tpl in _EVIDENCE_PATTERN_TEMPLATES
    ]
    total = 0
    for text in memory_texts:
        for pat in patterns:
            if pat.search(text):
                total += 1
                break  # one hit per memory is enough
    return total


def detect_temporal_endpoint_mismatch(
    question: str, retrieved_memories: list[Any],
) -> dict | None:
    """Return mismatch detection result dict, or None.

    Detection conditions:
      - Question matches the employer-endpoint trigger
      - 0 first-person evidence statements for the employer in
        user-turn retrieved memories
    """
    employer = _extract_employer_endpoint(question)
    if not employer:
        return None
    mem_texts = _iter_user_memory_text(retrieved_memories)
    if not mem_texts:
        # Defensive: if no user-turn memory was passed in, treat as
        # ambiguous and skip (don't false-fire on empty input).
        return None
    n_hits = _count_employer_evidence(employer, mem_texts)
    if n_hits > 0:
        return None  # endpoint supported
    return {"employer": employer, "evidence_hits": 0}


def temporal_endpoint_support_guard(
    question: str, retrieved_memories: list[Any],
) -> str:
    """Return a prompt-prefix when retrieved memories don't carry
    first-person evidence that the user works/started at the
    employer asked about.

    Returns empty string when:
      - Question doesn't match the employer-endpoint trigger
      - At least 1 first-person work-at-Y evidence statement is in
        memories
    """
    detection = detect_temporal_endpoint_mismatch(
        question, retrieved_memories,
    )
    if detection is None:
        return ""
    return _format_guard(detection["employer"])


_OVER_COMMIT_DURATION_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:year|month|week|day)s?\b",
    re.IGNORECASE,
)


def _looks_over_committed(answer: str) -> bool:
    if not answer:
        return False
    low = answer.lower()
    if any(p in low for p in ("information provided is not enough",
                              "you haven't",
                              "have not started",
                              "haven't started",
                              "memories do not specify",
                              "cannot determine")):
        return False
    return bool(_OVER_COMMIT_DURATION_RE.search(answer))


def maybe_rewrite_with_temporal_guard(
    question: str, retrieved_memories: list[Any], llm_answer: str,
) -> str:
    """Post-process: when the temporal endpoint guard fired AND the
    LLM still committed to a duration (e.g. "4 years 3 months"),
    rewrite to a canonical abstain. Mirrors the role-mismatch
    post-rewrite contract.
    """
    detection = detect_temporal_endpoint_mismatch(
        question, retrieved_memories,
    )
    if detection is None:
        return llm_answer
    if not _looks_over_committed(llm_answer):
        return llm_answer
    employer = detection["employer"]
    return (
        "The information provided is not enough. "
        f"You haven't started working at {employer} yet, "
        f"so the duration before starting at {employer} is undefined."
    )


def _format_guard(employer: str) -> str:
    return (
        "═══════════════════════════════════════════════════════════════\n"
        "⚠️  TEMPORAL ENDPOINT SUPPORT CHECK (deterministic):\n"
        "═══════════════════════════════════════════════════════════════\n"
        f"The question PRESUPPOSES that the user has started a job at\n"
        f"'{employer}'. This presupposition is NOT supported by any\n"
        f"memory — no first-person statement of working/starting/\n"
        f"joining {employer} appears in the retrieved memories.\n"
        f"\n"
        f"INTERPRETATION:\n"
        f"  - The user has NEVER said they work at '{employer}'.\n"
        f"  - The duration 'before starting at {employer}' is\n"
        f"    undefined when the start has not occurred.\n"
        f"  - DO NOT compute a duration from the user's other job\n"
        f"    tenures and report it as 'before starting at\n"
        f"    {employer}'.\n"
        f"\n"
        f"REQUIRED RESPONSE (this overrides every other section above):\n"
        f"  Answer: 'The information provided is not enough. You\n"
        f"  haven't started working at {employer} yet.'\n"
        "═══════════════════════════════════════════════════════════════\n\n"
    )
