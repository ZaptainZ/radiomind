"""Skill base class + result shape."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SkillResult:
    """One structured-layer answer. Format as prompt prefix via `prefix()`."""
    skill_name: str
    answer: str
    anchors: list[tuple[str, str]]  # (label, value) — evidence chain
    confidence: float = 1.0

    def prefix(self) -> str:
        lines = [
            f"STRUCTURED SKILL ({self.skill_name}, "
            f"conf={self.confidence:.2f}): trust this unless retrieval explicitly contradicts."
        ]
        for label, value in self.anchors[:5]:
            lines.append(f"- {label} → {value}")
        lines.append(f"Computed answer: {self.answer}")
        return "\n".join(lines) + "\n\n"


class Skill:
    """Base class for structured-layer resolvers.

    Subclasses implement:
      - name: short identifier
      - match(signature) → bool: whether this skill applies
      - resolve(query, memories, context) → SkillResult | None
    """
    name: str = "skill"
    priority: int = 100  # lower runs first

    def match(self, signature: Any) -> bool:
        return False

    def resolve(self, query: str, memories: list, context: dict) -> SkillResult | None:
        return None
