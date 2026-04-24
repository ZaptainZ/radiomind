"""Skill registry — ordered list, first-match wins."""
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


# Built-in registrations
def _bootstrap() -> None:
    from radiomind.skills import (  # noqa: F401
        temporal, cardinality, age_interval, event_interval,
        list_ordering, chain_reasoning,
    )


_bootstrap()
