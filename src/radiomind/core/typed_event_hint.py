"""V8.3.1: Typed-event arithmetic hint — person_age average.

Codex-locked scope (V8.3.1 pilot):
  - ONE typed event family: person_age{relation, age:int}
  - ONE operator: mean
  - ONE query family: "average age of me, my parents, my grandparents"
  - Closed kin set: {self, mom, dad, grandma, grandpa}
  - Hint-only; never rewrites the answer
  - Must extract the FULL kin set; missing one → no hint

Out of scope (do NOT extend in this commit):
  - charity / fundraise sum (V8.3.1b)
  - other aggregation operators (count_distinct, ordering)
  - non-kin averages (friends, colleagues, etc.)
  - historical / past-tense ages

The hint is prepended to the answer prompt as a TYPED EVENT HINT — not
a commit override. Same philosophy as V8.2.3a cashback_arithmetic_hint.
"""
from __future__ import annotations

import re
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Query trigger: "average age of me, my parents, my grandparents"
# ─────────────────────────────────────────────────────────────────────────────
# Must contain: avg keyword + "age" + reference to ALL THREE groups
# (me / parents / grandparents). All three present → fire; missing any → skip.
_AVG_KEYWORDS = re.compile(r"\b(?:average|avg|mean)\b", re.IGNORECASE)
_AGE_WORD = re.compile(r"\bage(?:s)?\b", re.IGNORECASE)
_ME_REF = re.compile(r"\b(?:me|i|my\s+age|myself)\b", re.IGNORECASE)
_PARENTS_REF = re.compile(r"\bparents?\b", re.IGNORECASE)
_GRANDPARENTS_REF = re.compile(r"\bgrand\s*parents?\b", re.IGNORECASE)


def _query_triggers(question: str) -> bool:
    """Return True iff query asks for the average age across the full kin set."""
    if not question:
        return False
    if not _AVG_KEYWORDS.search(question):
        return False
    if not _AGE_WORD.search(question):
        return False
    # All three group references must appear
    if not _ME_REF.search(question):
        return False
    if not _PARENTS_REF.search(question):
        return False
    if not _GRANDPARENTS_REF.search(question):
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Extraction: kin role + age
# ─────────────────────────────────────────────────────────────────────────────
# Closed kin alias table → canonical role
_KIN_ALIAS = {
    "mom": "mom", "mother": "mom", "mum": "mom", "mama": "mom", "mommy": "mom",
    "dad": "dad", "father": "dad", "papa": "dad", "daddy": "dad",
    "grandma": "grandma", "grandmother": "grandma", "nana": "grandma",
    "granny": "grandma", "gran": "grandma",
    "grandpa": "grandpa", "grandfather": "grandpa", "granddad": "grandpa",
    "gramps": "grandpa",
}

# Required kin roles for the V8.3.1 pilot
_REQUIRED_ROLES = frozenset({"self", "mom", "dad", "grandma", "grandpa"})

# Kin age pattern: "(my )?<role> is N" — present tense only.
# Past-tense ("was N") and bare "turned N" deliberately excluded → historical risk.
_KIN_AGE_RE = re.compile(
    r"\b(?:my\s+)?(mom|mother|mum|mama|mommy"
    r"|dad|father|papa|daddy"
    r"|grandma|grandmother|nana|granny|gran"
    r"|grandpa|grandfather|granddad|gramps)\s+is\s+(\d{1,3})\b",
    re.IGNORECASE,
)

# Self age pattern: "I am N" / "I'm N" / "I just turned N" / "I recently turned N"
# Conservative: require "just"/"recently" before "turned" OR a present-tense
# "am" / "'m" form. Past-tense "I was N" deliberately excluded.
# Note: "I'm" is one token (no space between I and 'm), so we handle the
# contraction form separately from the spaced "I am" form.
_SELF_AGE_RE = re.compile(
    r"\b(?:"
    r"I\s+am(?:\s+now)?"      # "I am N", "I am now N"
    r"|I'm(?:\s+now)?"         # "I'm N", "I'm now N"
    r"|I\s+just\s+turned"      # "I just turned N"
    r"|I\s+recently\s+turned"  # "I recently turned N"
    r")\s+(\d{1,3})\b",
    re.IGNORECASE,
)


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


def _extract_kin_ages(mem_texts: list[str]) -> dict[str, list[int]]:
    """Return {canonical_role: [ages]} extracted from memory texts.

    If a role appears with multiple distinct ages we keep them all so the
    caller can decide whether to refuse (ambiguous).
    """
    found: dict[str, list[int]] = {}
    for t in mem_texts:
        # Kin (mom/dad/grandma/grandpa)
        for m in _KIN_AGE_RE.finditer(t):
            alias = m.group(1).lower()
            canonical = _KIN_ALIAS.get(alias)
            if not canonical:
                continue
            try:
                age = int(m.group(2))
            except ValueError:
                continue
            if not 0 < age < 130:
                continue
            found.setdefault(canonical, []).append(age)
        # Self
        for m in _SELF_AGE_RE.finditer(t):
            try:
                age = int(m.group(1))
            except ValueError:
                continue
            if not 0 < age < 130:
                continue
            found.setdefault("self", []).append(age)
    return found


def _resolve_role_age(ages: list[int]) -> int | None:
    """Resolve a single age for a role from possibly-multiple mentions.

    Strategy: if all mentions agree → use that. If they disagree → refuse
    (return None) — we don't have temporal grounding in V8.3.1 to pick the
    current one.
    """
    if not ages:
        return None
    unique = set(ages)
    if len(unique) == 1:
        return next(iter(unique))
    return None  # ambiguous; refuse


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────
def person_age_average_hint(
    question: str,
    retrieved_memories: list[Any],
    mind: Any | None = None, domain: str | None = None,
) -> str:
    """Return a typed-event arithmetic hint, or "" if conditions don't fire.

    Fires only when ALL hold:
      1. Query asks for average age across me + parents + grandparents
      2. All 5 kin roles {self, mom, dad, grandma, grandpa} have an
         extractable, unambiguous age in retrieved memories
      3. All ages are plausible (0 < age < 130)

    SelfAnchor-1b: when the only missing role is `self` AND
    `mind`+`domain` are supplied, a targeted store scan recovers the
    user's own current age from the domain's user-turn layer (the
    self-age statement often ranks out of retrieve top-200). The
    scan is first-person only and surfaces its source turn_id +
    quote in the hint.

    Format:
      "TYPED EVENT HINT: ages found — self=32, mom=55, dad=58, grandma=75,
       grandpa=78; mean = (32+55+58+75+78)/5 = 59.6."
    """
    if not _query_triggers(question):
        return ""
    mems = _iter_memory_text(retrieved_memories)
    if not mems:
        return ""

    raw = _extract_kin_ages(mems)
    resolved: dict[str, int] = {}
    self_source = None  # (turn_id, quote, scan_scope)
    missing: list[str] = []
    for role in _REQUIRED_ROLES:
        age = _resolve_role_age(raw.get(role, []))
        if age is None:
            missing.append(role)
        else:
            resolved[role] = age

    # SelfAnchor-1b: recover ONLY a missing `self` age via store scan.
    # All kin roles must already be resolved from retrieve (we only
    # supplement the single self anchor, never kin).
    if missing == ["self"] and mind is not None and domain:
        from radiomind.core.self_anchor import scan_current_age_user_turns
        proof = scan_current_age_user_turns(mind, domain)
        if proof is not None:
            resolved["self"] = int(proof.value)
            self_source = (proof.source_turn_id, proof.quote, proof.scan_scope)
            missing = []

    if missing:
        return ""  # still missing/ambiguous — refuse hint

    # Compute mean
    values = [resolved[r] for r in ("self", "mom", "dad", "grandma", "grandpa")]
    total = sum(values)
    n = len(values)
    mean = total / n

    # Format mean to 1 decimal place, but trim trailing .0 if whole
    if abs(mean - round(mean)) < 1e-9:
        mean_str = f"{mean:.0f}"
    else:
        mean_str = f"{mean:.1f}"

    ages_str = ", ".join(
        f"{r}={resolved[r]}" for r in ("self", "mom", "dad", "grandma", "grandpa")
    )
    sum_expr = "+".join(str(v) for v in values)
    self_line = ""
    if self_source:
        self_line = (
            f"  (self age via SelfAnchor store-scan from turn "
            f"{self_source[0]}, scope={self_source[2]}, "
            f"quote={self_source[1]!r})\n"
        )
    return (
        "TYPED EVENT HINT (deterministic, from retrieved memories):\n"
        f"  Ages found: {ages_str}.\n"
        f"{self_line}"
        f"  Mean = ({sum_expr})/{n} = {total}/{n} = {mean_str}.\n"
        f"  If the question asks for the average age across me, my parents, "
        f"and my grandparents, the answer is {mean_str}.\n\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1.5 Diagnostic / Refusal-Reason Hook (read-only)
# ─────────────────────────────────────────────────────────────────────────────


def diagnose_person_age(
    question: str, retrieved_memories: list[Any],
) -> dict:
    """Parallel diagnostic for `person_age_average_hint`.

    Refusal-reason codes:
      - `no_trigger_match`
      - `no_user_memories`
      - `kin_role_missing`           (which role: in `missing_roles`)
      - `kin_role_age_ambiguous`     (multiple distinct ages for one role)
    """
    out: dict = {
        "fired": False, "refusal_reason": None,
        "kin_ages": {}, "missing_roles": [], "ambiguous_roles": [],
        "computed_mean": None,
    }
    if not _query_triggers(question):
        out["refusal_reason"] = "no_trigger_match"
        return out
    mems = _iter_memory_text(retrieved_memories)
    if not mems:
        out["refusal_reason"] = "no_user_memories"
        return out
    raw = _extract_kin_ages(mems)
    out["kin_ages_raw"] = dict(raw)
    missing: list[str] = []
    ambiguous: list[str] = []
    resolved: dict[str, int] = {}
    for role in _REQUIRED_ROLES:
        ages = raw.get(role, [])
        if not ages:
            missing.append(role)
            continue
        if len(set(ages)) > 1:
            ambiguous.append(role)
            continue
        age = _resolve_role_age(ages)
        if age is None:
            ambiguous.append(role)
            continue
        resolved[role] = age
    if missing:
        out["refusal_reason"] = "kin_role_missing"
        out["missing_roles"] = missing
        out["kin_ages"] = resolved
        return out
    if ambiguous:
        out["refusal_reason"] = "kin_role_age_ambiguous"
        out["ambiguous_roles"] = ambiguous
        out["kin_ages"] = resolved
        return out
    out["fired"] = True
    out["kin_ages"] = resolved
    values = [resolved[r] for r in _REQUIRED_ROLES]
    out["computed_mean"] = sum(values) / len(values)
    return out
