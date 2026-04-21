"""Cardinality skill — wraps NumericAggregator's cardinal cache for count queries."""
from __future__ import annotations

from typing import Any

from radiomind.skills.base import Skill, SkillResult


class CardinalitySkill(Skill):
    """Reads ingest-time cardinal cache. Lives alongside get_numeric_cardinal;
    the skill interface lets the registry compose it with other skills.

    Unlike TemporalSkill, this one needs access to mind's NumericAggregator;
    it's injected via context['mind'].
    """
    name = "cardinality"
    priority = 20

    def match(self, signature: Any) -> bool:
        return getattr(signature, "wants", "") == "count"

    def resolve(self, query: str, memories: list, context: dict) -> SkillResult | None:
        mind = context.get("mind")
        domain = context.get("domain", "")
        user_id = context.get("user_id", "")
        if mind is None:
            return None
        try:
            view = mind.get_numeric_cardinal(
                query=query, domain=domain, user_id=user_id,
            )
        except Exception:
            return None
        if not view:
            return None
        # view already contains a formatted block; wrap in SkillResult
        # without further anchor decomposition
        return SkillResult(
            skill_name=self.name,
            answer=view.strip().split("\n")[-1] if view.strip() else "",
            anchors=[("see DRAFT CARDINAL VIEW below", "injected")],
            confidence=0.95,
        )

    def resolve_raw(self, query: str, context: dict) -> str:
        """Return the raw cardinal view string (preferred — keeps existing format)."""
        mind = context.get("mind")
        if mind is None:
            return ""
        try:
            return mind.get_numeric_cardinal(
                query=query,
                domain=context.get("domain", ""),
                user_id=context.get("user_id", ""),
            )
        except Exception:
            return ""


from radiomind.skills.registry import register  # noqa: E402

register(CardinalitySkill())
