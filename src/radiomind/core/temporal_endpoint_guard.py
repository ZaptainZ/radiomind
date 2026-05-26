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


# TESG-1b (Codex 2026-05-26 P1.1): split the trigger into an
# IGNORECASE prefix and a CASE-SENSITIVE employer capture.
#
# The earlier single-regex version applied IGNORECASE to the entire
# pattern, making the `[A-Z]` employer constraint vacuous —
# `... at somewhere?` and `... at the company?` both triggered. By
# matching the prefix first (IGNORECASE) and then a Title-Cased
# employer noun on the remainder (case-sensitive), we restrict the
# trigger to real brand names.
_TRIGGER_PREFIX_RE = re.compile(
    r"how\s+long\s+(?:have|has|did|do)\s+i\s+\S+(?:\s+\S+){0,3}?\s+"
    r"before\s+i\s+(?:start|join|begin|began|got|landed|accept|"
    r"accepted)\w*\s+"
    r"(?:my\s+|the\s+|a\s+)?(?:current\s+|new\s+)?"
    r"(?:job|role|position|gig|work)\s+"
    r"(?:at|with|for|in)\s+",
    re.IGNORECASE,
)
# Employer is a Title-Cased noun (up to 3 tokens). Case-sensitive on
# purpose — lowercase generics like 'somewhere' / 'the company' / 'a
# friend' MUST NOT trigger this guard.
_EMPLOYER_RE = re.compile(
    r"\A([A-Z][\w&]*(?:\s+[A-Z][\w&]*){0,2})",
)


# TESG-1c (Codex 2026-05-26 third review): explicit-negative or
# future/planning evidence about the employer. ONLY when at least
# one of these patterns is found in retrieved+store text are we
# allowed to assert "user hasn't started" — that claim then has
# actual textual support. Absence of positive evidence is NOT
# negative evidence (FACT extraction can miss raw turns, store
# scan caps at 500, etc.).
_NEGATIVE_FUTURE_PATTERN_TEMPLATES = (
    # Explicit "haven't started at X" / "have not joined X yet"
    r"\bi\s+(?:haven'?t|have\s+not|did\s+not|didn'?t)\s+"
    r"(?:yet\s+)?(?:start|join|begin|begun)\w*\s+"
    r"(?:at|with|working\s+at|working\s+for)\s+{Y}\b",
    r"\bhave\s+not\s+(?:yet\s+)?started\s+(?:working\s+)?"
    r"(?:at|for|with)\s+{Y}\b",
    # Planning / intending / hoping to join Y (with optional
    # "at/for/with/to/in" preposition before Y, since "join Y"
    # also valid English).
    r"\bi(?:'m|\s+am)?\s+(?:plan|planning|hope|hoping|"
    r"intend|intending|going)\s+to\s+(?:join|work|start|"
    r"move\s+to)\s+(?:at|for|with|to|in\s+)?{Y}\b",
    # Interview / interviewing at/with Y — strong job-context signal
    r"\b(?:interview|interviewing|interviews?)\s+(?:at|with|for)\s+{Y}\b",
    # Applied / received offer / accepted offer at/with/from Y
    r"\bi(?:'ve|\s+have|\s+had)?\s+(?:applied|received|"
    r"accepted|got)\s+(?:an?\s+)?(?:job\s+|offer\s+|position\s+|"
    r"role\s+)?(?:at|for|from|with)\s+{Y}\b",
    # "An upcoming interview at Y" / "the interview at Y" — common
    # phrasings for job-search context
    r"\b(?:an?|the)\s+(?:upcoming\s+)?interview\s+(?:at|with)\s+{Y}\b",
    # Starting at Y next [time period] — explicit future start
    r"\b(?:start|starting|join|joining|begin|beginning)\s+"
    r"(?:at|with|for)\s+{Y}\s+(?:next|on|in|starting|this)\s+\w+",
)


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
    """Return the Title-Cased employer noun Y from a 'before I
    started ... at Y' question, or None when the question isn't this
    shape OR Y isn't capitalized.

    Two-stage match:
      1. IGNORECASE prefix locates the position right after `at`.
      2. Case-sensitive `[A-Z][\\w&]*` ensures Y is a real
         Title-Cased brand name; lowercase generics
         (`somewhere`, `the company`, `acme corp`) DO NOT trigger.
    """
    if not question:
        return None
    m_prefix = _TRIGGER_PREFIX_RE.search(question)
    if not m_prefix:
        return None
    remainder = question[m_prefix.end():]
    m_emp = _EMPLOYER_RE.match(remainder)
    if not m_emp:
        return None
    y = m_emp.group(1).strip()
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


def _has_explicit_negative_or_future(
    employer: str, memory_texts: list[str],
) -> bool:
    """True iff explicit negative-presence or future/planning
    evidence about the employer is found in the texts.

    TESG-1c: only when this returns True can the guard/rewrite
    assert "user haven't started at Y" — otherwise it must stay at
    "available evidence does not establish the endpoint".
    """
    if not employer or not memory_texts:
        return False
    y_escaped = re.escape(employer)
    patterns = [
        re.compile(tpl.format(Y=y_escaped), re.IGNORECASE)
        for tpl in _NEGATIVE_FUTURE_PATTERN_TEMPLATES
    ]
    for text in memory_texts:
        for pat in patterns:
            if pat.search(text):
                return True
    return False


def _iter_user_store_text(mind: Any, domain: str | None) -> list[str]:
    """List user-turn content strings from the full domain FACT store.

    Used as the support-aware fallback in
    `detect_temporal_endpoint_mismatch`: when retrieved memories have
    0 employer evidence, we MUST consult the full store before
    asserting "user never said they work at Y" — retrieval may simply
    have missed a relevant turn.
    """
    if mind is None or not getattr(mind, "_store", None) or not domain:
        return []
    try:
        from radiomind.core.types import MemoryLevel
        facts = mind._store.list_by_domain(
            domain, level=MemoryLevel.FACT, limit=500,
        )
    except Exception:
        return []
    out: list[str] = []
    for entry in facts:
        content = entry.content or ""
        c_low = content.lower()
        if "[assistant]" in c_low:
            continue
        if content:
            out.append(content)
    return out


def detect_temporal_endpoint_mismatch(
    question: str,
    retrieved_memories: list[Any],
    mind: Any | None = None,
    domain: str | None = None,
) -> dict | None:
    """Return mismatch detection result dict, or None.

    TESG-1c (Codex 2026-05-26 third review): the contract distinguishes
    TWO things that earlier versions conflated:

    - **support absence** (no positive employer evidence found in
      retrieved+store). Justifies emitting
      "available evidence does not establish the endpoint" — a
      claim about THIS PIPELINE'S evidence, not about reality.
    - **explicit negative or future-plan evidence** (e.g. "I plan
      to join Y", "I haven't started at Y yet", "interviewing at
      Y"). Justifies the stronger
      "user haven't started yet" rewrite — that claim now has
      direct textual support.

    Store scan (FACT layer, capped at 500) is NOT exhaustive proof
    of absence — raw turns can miss promotion to FACT, and the cap
    is not enforced as proof. The store check only SUPPRESSES the
    guard when it finds positive evidence; it does NOT upgrade
    absence to assertion.

    Detection conditions (in order):
      1. Question matches Title-Cased employer-endpoint trigger
      2. 0 first-person work-at-Y statements in retrieved memories
      3. (when mind+domain) 0 such statements in domain FACT store
      4. ≥1 retrieved memory was passed in (defensive)

    Returns:
      None when any of (1)-(4) fail.
      {employer, evidence_hits=0, has_explicit_negative: bool}
      otherwise.
    """
    employer = _extract_employer_endpoint(question)
    if not employer:
        return None
    mem_texts = _iter_user_memory_text(retrieved_memories)
    if not mem_texts:
        return None  # defensive
    if _count_employer_evidence(employer, mem_texts) > 0:
        return None  # supported by retrieved memories

    store_texts: list[str] = []
    if mind is not None and domain:
        store_texts = _iter_user_store_text(mind, domain)
        if store_texts and _count_employer_evidence(
            employer, store_texts,
        ) > 0:
            return None  # supported by store

    # No positive support found in retrieved or store. Decide whether
    # we ALSO have explicit-negative/future-plan evidence — that's
    # what unlocks the stronger "haven't started" rewrite. Absence
    # of FACT alone does NOT.
    all_texts = mem_texts + store_texts
    has_explicit_negative = _has_explicit_negative_or_future(
        employer, all_texts,
    )

    return {
        "employer": employer,
        "evidence_hits": 0,
        "has_explicit_negative": has_explicit_negative,
    }


def temporal_endpoint_support_guard(
    question: str,
    retrieved_memories: list[Any],
    mind: Any | None = None,
    domain: str | None = None,
) -> str:
    """Return a prompt-prefix when neither the retrieved memories
    nor the full domain store (when available) carry first-person
    evidence that the user works/started at the employer asked
    about.

    Returns empty string when:
      - Question doesn't match the Title-Cased employer trigger
      - At least 1 first-person work-at-Y evidence statement is in
        retrieved memories OR the full domain store
    """
    detection = detect_temporal_endpoint_mismatch(
        question, retrieved_memories, mind=mind, domain=domain,
    )
    if detection is None:
        return ""
    return _format_guard(
        detection["employer"],
        detection.get("has_explicit_negative", False),
    )


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
    question: str,
    retrieved_memories: list[Any],
    llm_answer: str,
    mind: Any | None = None,
    domain: str | None = None,
) -> str:
    """Post-process: when the temporal endpoint guard fired AND the
    LLM still committed to a duration (e.g. "4 years 3 months"),
    rewrite to canonical abstain.

    TESG-1c: rewrite wording reflects what evidence we ACTUALLY have:
      - explicit negative/future-plan evidence → "you haven't
        started at Y" (textual support exists).
      - no positive evidence found anywhere → "available evidence
        does not establish that you have started at Y" (claim is
        about the pipeline's evidence, not about reality).
    """
    detection = detect_temporal_endpoint_mismatch(
        question, retrieved_memories, mind=mind, domain=domain,
    )
    if detection is None:
        return llm_answer
    if not _looks_over_committed(llm_answer):
        return llm_answer
    employer = detection["employer"]
    if detection.get("has_explicit_negative"):
        return (
            "The information provided is not enough. "
            f"You haven't started working at {employer} yet, "
            f"so the duration before starting at {employer} is undefined."
        )
    return (
        "The information provided is not enough. The available "
        f"evidence does not establish that you have started working "
        f"at {employer}, so a duration before that endpoint cannot "
        f"be determined."
    )


def _format_guard(
    employer: str, has_explicit_negative: bool,
) -> str:
    """Render the prompt-prefix guard.

    TESG-1c contract: the assertive wording ("haven't started") is
    used ONLY when explicit-negative/future-plan textual evidence
    has been detected. Default is evidence-insufficient wording
    that claims only about the pipeline's evidence, not about
    reality. Absence of FACT matches is NOT proof of absence in
    the underlying conversation — FACT extraction can miss raw
    turns and the store scan caps at 500.
    """
    if has_explicit_negative:
        absence_line = (
            f"  - The user has explicitly indicated NOT-YET / "
            f"planning / interviewing status\n"
            f"    for '{employer}' — direct textual evidence "
            f"supports 'haven\\'t started'."
        )
        no_start_line = (
            f"  - The duration 'before starting at {employer}' is\n"
            f"    undefined when the start has not occurred."
        )
        required_response = (
            f"  Answer: 'The information provided is not enough. "
            f"You\n  haven't started working at {employer} yet.'"
        )
        header_note = "explicit-negative-evidence detected"
    else:
        absence_line = (
            f"  - Available evidence does not establish that the\n"
            f"    user has started at '{employer}' — but absence\n"
            f"    of evidence is not proof of absence (FACT\n"
            f"    extraction may miss raw turns; store scan is\n"
            f"    capped). Do NOT make positive factual claims."
        )
        no_start_line = (
            f"  - The duration 'before starting at {employer}'\n"
            f"    cannot be computed from the available evidence."
        )
        required_response = (
            f"  Answer: 'The information provided is not enough.'"
        )
        header_note = "evidence-insufficient (default)"
    return (
        "═══════════════════════════════════════════════════════════════\n"
        f"⚠️  TEMPORAL ENDPOINT SUPPORT CHECK ({header_note}):\n"
        "═══════════════════════════════════════════════════════════════\n"
        f"The question PRESUPPOSES that the user has started a job at\n"
        f"'{employer}'. This presupposition is NOT supported by any\n"
        f"first-person statement of working/starting/joining {employer}.\n"
        f"\n"
        f"INTERPRETATION:\n"
        f"{absence_line}\n"
        f"{no_start_line}\n"
        f"  - DO NOT compute a duration from the user's other job\n"
        f"    tenures and report it as 'before starting at\n"
        f"    {employer}'.\n"
        f"\n"
        f"REQUIRED RESPONSE (this overrides every other section above):\n"
        f"{required_response}\n"
        "═══════════════════════════════════════════════════════════════\n\n"
    )
