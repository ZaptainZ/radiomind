"""Skill registry — hard routing (first-match) and soft routing (trinity vote).

`try_resolve` is the hard variant: skills are tried by ascending priority,
the first one whose `match(signature)` returns True AND whose `resolve()`
yields a SkillResult wins. Fast, deterministic, right when exactly one
skill type is plausible.

`try_resolve_soft` (GAP-3) collects ALL matching skills' resolutions,
then fires a trinity vote to pick the best output when more than one
skill produced a SkillResult. Handles cases where hard routing fires
the wrong skill — e.g. a music-genre question that matches `temporal`
on surface tokens (and abstains) when `chain_reasoning` would have
handled it correctly.
"""
from __future__ import annotations

from typing import Any

from radiomind.skills.base import Skill, SkillResult


REGISTRY: list[Skill] = []


def register(skill: Skill) -> None:
    REGISTRY.append(skill)
    REGISTRY.sort(key=lambda s: s.priority)


def try_resolve(
    query: str,
    memories: list,
    signature: Any,
    context: dict | None = None,
) -> SkillResult | None:
    """Return the first matching skill's result; None if no skill applies."""
    ctx = context or {}
    for skill in REGISTRY:
        try:
            if not skill.match(signature):
                continue
            result = skill.resolve(query, memories, ctx)
            if result is not None:
                return result
        except Exception:
            continue
    return None


def try_resolve_soft(
    query: str,
    memories: list,
    signature: Any,
    context: dict | None = None,
) -> SkillResult | None:
    """Soft routing: all matching skills resolve in parallel; trinity
    votes which output to use when there are multiple candidates.

    Behavior:
      - 0 candidates → None (same as hard routing)
      - 1 candidate  → return it (no trinity cost)
      - 2+ candidates → trinity votes; falls back to highest-confidence
        candidate when the LLM is unavailable or the vote is unparseable

    Trinity stances are picked per-call but the task description biases
    toward three independent dimensions: structural-fit (skill matches
    question verb/interrogative shape) / evidence-strength (anchors,
    confidence) / answer-shape (skill output matches expected shape).
    """
    ctx = context or {}
    candidates: list[SkillResult] = []
    for skill in REGISTRY:
        try:
            if not skill.match(signature):
                continue
            result = skill.resolve(query, memories, ctx)
            if result is not None:
                candidates.append(result)
        except Exception:
            continue

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    mind = ctx.get("mind") if ctx else None
    llm = getattr(mind, "_llm", None) if mind is not None else None
    if llm is None:
        return max(candidates, key=lambda r: r.confidence)
    try:
        if not llm.is_available():
            return max(candidates, key=lambda r: r.confidence)
    except Exception:
        return max(candidates, key=lambda r: r.confidence)

    from radiomind.refinement.trinity import debate
    ev_lines = []
    for i, r in enumerate(candidates):
        ev_lines.append(
            f"CANDIDATE_{i} skill={r.skill_name} conf={r.confidence:.2f}"
        )
        ev_lines.append(f"  answer: {(r.answer or '')[:300]}")
        for label, value in (r.anchors or [])[:3]:
            ev_lines.append(f"  {label}: {value}")
    evidence = "\n".join(ev_lines)
    result = debate(
        task=(
            f"Multiple skills produced answers for this question; pick "
            f"the BEST one. Three stances triangulate:\n"
            f"  structural-fit — which skill matches the question's "
            f"verb / interrogative shape\n"
            f"  evidence-strength — which candidate has the strongest "
            f"anchors / highest confidence\n"
            f"  answer-shape — which candidate's answer matches the "
            f"answer shape the question expects (number / date / "
            f"named entity / sentence)\n"
            f"Output the chosen CANDIDATE index (0-based).\n"
            f"\nQuestion: {query}"
        ),
        evidence=evidence,
        llm=llm,
        extra_schema='  "chosen_index": int',
    )
    if not result:
        return max(candidates, key=lambda r: r.confidence)
    try:
        idx = int(result.get("chosen_index"))
    except (TypeError, ValueError):
        return max(candidates, key=lambda r: r.confidence)
    if 0 <= idx < len(candidates):
        return candidates[idx]
    return max(candidates, key=lambda r: r.confidence)


# Built-in registrations
def _bootstrap() -> None:
    from radiomind.skills import (  # noqa: F401
        temporal, cardinality, age_interval, event_interval,
        list_ordering, chain_reasoning,
    )


_bootstrap()
