"""SimpleRadioMind — the "just works" entry point.

Mem0-style simplicity: add, search, digest, refine. That's it.
All bionic internals (3D pyramid, HDC, three-body debate, dream pruning)
happen automatically behind these 4 methods.

Usage:
    from radiomind import simple

    mind = simple.connect()
    mind.add([{"role": "user", "content": "I like running"}])
    results = mind.search("exercise")
    print(mind.digest())

Or even simpler:
    import radiomind
    mind = radiomind.connect()
"""

from __future__ import annotations

from radiomind.core.config import Config
from radiomind.core.mind import RadioMind
from radiomind.core.types import Message
from radiomind.protocol import AddResult, Memory, RefineResult


class SimpleRadioMind:
    """4-method interface to RadioMind's bionic memory.

    Implements radiomind.protocol.MemoryProtocol.
    """

    def __init__(self, home: str | None = None, config_path: str | None = None):
        from pathlib import Path

        cfg = Config.load(Path(config_path) if config_path else None)
        if home:
            cfg.set("general.home", home)
        self._mind = RadioMind(config=cfg)
        self._mind.initialize()

    def add(
        self,
        messages: list[dict[str, str]],
        user_id: str = "",
    ) -> AddResult:
        """Add conversation messages to memory.

        >>> mind.add([
        ...     {"role": "user", "content": "I like running"},
        ...     {"role": "assistant", "content": "That's great for health!"},
        ... ])
        AddResult(added=1, skipped=0)
        """
        msgs = [
            Message(
                role=m.get("role", "user"),
                content=m.get("content", ""),
            )
            for m in messages
        ]
        entries = self._mind.ingest(msgs)
        return AddResult(added=len(entries), skipped=len(msgs) - len(entries))

    def search(
        self,
        query: str,
        limit: int = 10,
        domain: str | None = None,
    ) -> list[Memory]:
        """Search memories.

        >>> results = mind.search("exercise")
        >>> results[0].content
        'I like running'
        """
        results = self._mind.search(query, domain=domain)
        habits = self._mind.query_habits(query)

        memories = []
        for r in results[:limit]:
            memories.append(Memory(
                content=r.entry.content,
                domain=r.entry.domain,
                level=r.entry.level.name.lower(),
                score=r.score,
                metadata=r.entry.metadata,
            ))

        for h in habits[:3]:
            memories.append(Memory(
                content=h.description,
                domain="habits",
                level="habit",
                score=h.confidence,
                metadata={"status": h.status.value},
            ))

        return memories[:limit]

    def digest(self, token_budget: int = 250) -> str:
        """Get context digest for system prompt injection.

        >>> print(mind.digest())
        User: name: Alice
        Style: prefers morning work
        Memory: 42 entries across work, health
        """
        return self._mind.get_context_digest(token_budget=token_budget)

    def refine(self, domain: str | None = None) -> RefineResult:
        """Run a refinement cycle (three-body debate + dream pruning).

        Returns empty result if no LLM backend is available.
        """
        if not self._mind._llm or not self._mind._llm.is_available():
            return RefineResult()

        insights = 0
        merged = pruned = 0
        duration = 0.0

        try:
            chat_result = self._mind.trigger_chat(domain=domain)
            insights += len(chat_result.new_insights)
            duration += chat_result.duration_s
        except Exception:
            pass

        try:
            dream_result = self._mind.trigger_dream()
            insights += len(dream_result.new_insights)
            merged = dream_result.merged
            pruned = dream_result.pruned
            duration += dream_result.duration_s
        except Exception:
            pass

        return RefineResult(insights=insights, merged=merged, pruned=pruned, duration_s=duration)

    def close(self) -> None:
        """Shut down RadioMind."""
        self._mind.shutdown()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # --- Expose advanced API for power users ---

    @property
    def advanced(self) -> RadioMind:
        """Access the full RadioMind API for advanced operations.

        >>> mind.advanced.trigger_dream()
        >>> mind.advanced.get_user_profile()
        >>> mind.advanced.train(iters=100)
        """
        return self._mind


def connect(
    home: str | None = None,
    config_path: str | None = None,
) -> SimpleRadioMind:
    """One-line connection to RadioMind.

    >>> import radiomind
    >>> mind = radiomind.connect()
    """
    return SimpleRadioMind(home=home, config_path=config_path)
