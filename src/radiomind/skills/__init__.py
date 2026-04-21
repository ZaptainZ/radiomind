"""Structured-layer skills — deterministic resolvers tried before LLM.

The principle: if a task reduces to computation over structured metadata
(session_date, entity_class counts, named entities in retrieved content),
solve it deterministically here. Trinity + answer LLM remain the fallback
for genuinely ambiguous queries. This module is the "structured layer
before LLM layer" doctrine made explicit.
"""

from radiomind.skills.base import Skill, SkillResult
from radiomind.skills.registry import REGISTRY, try_resolve

__all__ = ["Skill", "SkillResult", "REGISTRY", "try_resolve"]
