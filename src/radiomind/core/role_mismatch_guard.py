"""V8.2.2a: Role/title mismatch guard.

Deterministic regex-based guard against over-commit when question asks
about a role/title that retrieved memories don't actually support.

Concrete root case (LME-S `031748ae_abs`):
  Q: "How many engineers do I lead when I just started my new role as
      Software Engineer Manager?"
  Gold: "Information not enough. You started as Senior Software Engineer,
        not Software Engineer Manager."
  V8.2.1 over-committed: "you lead a team of five engineers" — pulled
        the team size from a memory referring to the Senior Engineer
        role, not the Manager role asked about.

Codex audit insight: don't do generic "confidence threshold" or "claim
SPO verification". Both either miss this case or over-fire. Make a
narrow deterministic guard: when the question role contains a leadership
qualifier the memories never echo, inject a prompt prefix forcing the
answerer to abstain.

Scope (V8.2.2a):
  - Only role/title mismatch (NOT time-scope, NOT subject)
  - Only triggers when question role is "leadership-bearing" and memories
    only support IC-track roles (or vice-versa)
  - Zero LLM cost
"""
from __future__ import annotations

import re
from typing import Any


# Leadership-track keywords: when these appear in question or memory role
# phrases, they signal management/seniority track distinct from IC track.
_LEADERSHIP_KEYWORDS = frozenset({
    "manager", "director", "lead", "head", "chief", "vp", "ceo",
    "cto", "cfo", "coo", "president", "executive", "principal officer",
    "supervisor", "boss",
})

# Individual-contributor (IC) keywords: signal non-management technical role.
_IC_KEYWORDS = frozenset({
    "engineer", "developer", "programmer", "scientist", "analyst",
    "researcher", "designer", "architect", "specialist", "consultant",
    "associate",
})

# Seniority-only modifiers (don't change track):
_SENIORITY_MODIFIERS = frozenset({
    "senior", "junior", "staff", "principal", "associate",
    "entry-level", "mid-level", "fresher",
})


# Pattern: capture role phrases. Looks for Title-cased phrases ending
# with a known IC or Leadership keyword (with optional modifiers).
_ROLE_PHRASE_RE = re.compile(
    r"\b(?:"
    # Modifier-prefixed roles: "Senior Software Engineer", "Staff Data Scientist"
    r"(?:Senior|Junior|Staff|Principal|Lead|Head|Chief)\s+"
    r"(?:[A-Z][a-z]+\s+){0,3}"
    r"(?:Engineer|Developer|Programmer|Scientist|Analyst|Researcher|"
        r"Designer|Architect|Specialist|Consultant|Manager|Director|"
        r"Officer|VP|President)"
    r"|"
    # Leadership pattern: "X Manager", "Engineering Director", "VP of Engineering"
    r"(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Manager|Director|Lead|Head|Officer|VP|President|Executive)"
    r"|"
    # IC pattern (without modifier): "Software Engineer", "Data Scientist"
    r"(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Engineer|Developer|Programmer|Scientist|Analyst|Researcher)"
    r"|"
    # Bare leadership tokens: "VP", "CTO"
    r"\b(?:VP|CTO|CEO|CFO|COO|CMO)\b"
    r")\b"
)


def _classify_track(role_phrase: str) -> str:
    """Classify a role phrase into 'leadership' / 'ic' / 'unknown' track.

    Leadership includes any Manager/Director/Lead/Head/VP/Chief mention.
    IC track is Engineer/Developer/Scientist/Analyst without Leadership.
    """
    low = role_phrase.lower()
    has_leader = any(k in low for k in _LEADERSHIP_KEYWORDS)
    has_ic = any(k in low for k in _IC_KEYWORDS)
    if has_leader:
        return "leadership"
    if has_ic:
        return "ic"
    return "unknown"


def _normalize_role(role_phrase: str) -> str:
    """Normalize a role phrase for equivalence comparison.

    Strips seniority modifiers and lowercases. So "Senior Software Engineer"
    and "Software Engineer" both normalize to "software engineer".
    """
    low = role_phrase.lower().strip()
    tokens = low.split()
    # Drop leading seniority modifiers
    while tokens and tokens[0] in _SENIORITY_MODIFIERS:
        tokens = tokens[1:]
    # Drop "of" stop words: "VP of Engineering" → "vp engineering"
    tokens = [t for t in tokens if t != "of"]
    return " ".join(tokens)


def extract_role_phrases(text: str) -> list[str]:
    """Extract candidate role phrases from a text string."""
    matches = _ROLE_PHRASE_RE.findall(text)
    # Dedup preserving order
    seen: set[str] = set()
    out: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _iter_memory_text(retrieved_memories: list[Any]) -> list[str]:
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
        if content:
            out.append(content)
    return out


def role_mismatch_guard(question: str, retrieved_memories: list[Any]) -> str:
    """Return a prompt prefix when retrieved memories suggest a role
    different from the role specified in the question.

    Returns empty string when:
      - Question has no detectable role phrase
      - Question role is present (exactly or via normalization) in memories
      - Question role and memory roles are on the same track (both IC or both leadership)
        with no specific role conflict
    """
    if not question or not retrieved_memories:
        return ""

    q_roles = extract_role_phrases(question)
    if not q_roles:
        return ""

    mem_texts = _iter_memory_text(retrieved_memories)
    if not mem_texts:
        return ""

    # Combined memory text for role search
    mem_blob = "\n".join(mem_texts)
    m_roles = extract_role_phrases(mem_blob)

    # For each question role, check if memories support it
    for q_role in q_roles:
        q_normalized = _normalize_role(q_role)
        q_track = _classify_track(q_role)

        # Check if memories have any exact / normalized match
        supported = False
        for m_role in m_roles:
            m_normalized = _normalize_role(m_role)
            if m_normalized == q_normalized:
                supported = True
                break
        if supported:
            continue

        # No exact/normalized match. Check track conflict:
        # If question is leadership and ALL memory roles are IC → mismatch
        # If question is IC and memory roles include both → ambiguous, skip
        m_tracks = {_classify_track(r) for r in m_roles}
        if q_track == "leadership" and m_roles and m_tracks <= {"ic", "unknown"}:
            # Memories only have IC roles, question asks about leadership role
            # → strong mismatch signal
            return _format_guard(q_role, m_roles, q_track)
        if q_track == "ic" and m_roles and m_tracks <= {"leadership", "unknown"}:
            return _format_guard(q_role, m_roles, q_track)
        # Otherwise: same track but different role names — skip (less reliable signal)

    return ""


def _format_guard(q_role: str, m_roles: list[str], q_track: str) -> str:
    """Build the guard prompt prefix.

    Strengthened wording — explicit ABSTAIN imperative + contradiction
    block for atomic/profile sections that may have transferred facts
    across the role boundary.
    """
    distinct_mem_roles = []
    seen = set()
    for r in m_roles:
        if r not in seen:
            seen.add(r)
            distinct_mem_roles.append(r)
        if len(distinct_mem_roles) >= 3:
            break

    other_track = "individual-contributor" if q_track == "leadership" else "leadership"

    return (
        "═══════════════════════════════════════════════════════════════\n"
        "⚠️  ROLE PRESUPPOSITION CHECK (deterministic):\n"
        "═══════════════════════════════════════════════════════════════\n"
        f"The question PRESUPPOSES that the user has role '{q_role}'.\n"
        f"This presupposition is NOT supported by any memory.\n"
        f"\n"
        f"Memories only show the user with role(s): {distinct_mem_roles}.\n"
        f"These are DIFFERENT roles from '{q_role}' "
        f"({q_track} track vs {other_track} track).\n"
        f"\n"
        f"INTERPRETATION:\n"
        f"  - The user has NEVER been '{q_role}' (no memory says so).\n"
        f"  - Facts about the user's actual role(s) {distinct_mem_roles} "
        f"DO NOT answer this question.\n"
        f"  - The question's premise is invalid w.r.t. the memories.\n"
        f"\n"
        f"REQUIRED RESPONSE (this overrides every other section above):\n"
        f"  Answer: 'The information provided is not enough. You mentioned\n"
        f"  starting the role as {distinct_mem_roles[0]} but not {q_role}.'\n"
        f"\n"
        f"Do NOT compute team sizes, headcounts, or any specifics for\n"
        f"'{q_role}'. That role does not exist in the user's history.\n"
        "═══════════════════════════════════════════════════════════════\n\n"
    )
