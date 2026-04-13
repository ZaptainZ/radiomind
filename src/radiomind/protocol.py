"""RadioMind Protocol — the formal interface contract.

Any memory backend that implements this Protocol can be used as a RadioMind provider.
This is the "Layer 1" API — 4 methods is all you need.

Usage:
    from radiomind.protocol import MemoryProtocol

    def my_agent(memory: MemoryProtocol):
        memory.add([{"role": "user", "content": "I like running"}])
        results = memory.search("exercise")
        digest = memory.digest()
        memory.refine()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Memory:
    """A single memory entry returned by search."""
    content: str
    domain: str = ""
    level: str = "fact"  # fact | pattern | principle
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AddResult:
    """Result of adding memories."""
    added: int
    skipped: int = 0


@dataclass
class RefineResult:
    """Result of a refinement cycle."""
    insights: int = 0
    merged: int = 0
    pruned: int = 0
    duration_s: float = 0.0


@runtime_checkable
class MemoryProtocol(Protocol):
    """The universal RadioMind interface — 4 methods.

    Any framework can depend on this Protocol without importing RadioMind internals.
    """

    def add(
        self,
        messages: list[dict[str, str]],
        user_id: str = "",
    ) -> AddResult:
        """Add conversation messages to memory.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            user_id: Optional user identifier for multi-user scenarios.

        Returns:
            AddResult with count of added and skipped entries.
        """
        ...

    def search(
        self,
        query: str,
        limit: int = 10,
        domain: str | None = None,
    ) -> list[Memory]:
        """Search memories using pyramid retrieval (principles → patterns → facts).

        Args:
            query: Search query (supports Chinese and English).
            limit: Maximum results to return.
            domain: Optional domain filter.

        Returns:
            List of Memory objects sorted by relevance.
        """
        ...

    def digest(self, token_budget: int = 250) -> str:
        """Generate a context digest for system prompt injection.

        Args:
            token_budget: Approximate token limit for the digest.

        Returns:
            Compressed summary of user profile + active domains + system state.
        """
        ...

    def refine(self, domain: str | None = None) -> RefineResult:
        """Run a refinement cycle (chat debate + dream pruning).

        Args:
            domain: Optional domain to focus on. None = all active domains.

        Returns:
            RefineResult with counts of insights, merges, and prunes.
        """
        ...
