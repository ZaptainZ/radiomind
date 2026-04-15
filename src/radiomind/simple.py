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

    def __init__(
        self,
        home: str | None = None,
        config_path: str | None = None,
        llm=None,
    ):
        """Initialize SimpleRadioMind.

        Args:
            home: Data directory (default: ~/.radiomind).
            config_path: Path to config.toml.
            llm: External LLM callable: (prompt: str, system: str) → str.
                 When provided, RadioMind uses this for refinement instead of
                 requiring its own LLM config. Pass your framework's LLM here.
        """
        from pathlib import Path

        cfg = Config.load(Path(config_path) if config_path else None)
        if home:
            cfg.set("general.home", home)
        self._mind = RadioMind(config=cfg, llm=llm)
        self._mind.initialize()

    def add(
        self,
        messages: list[dict[str, str]],
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
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
        entries = self._mind.ingest(
            msgs, user_id=user_id, agent_id=agent_id, session_id=session_id
        )
        return AddResult(added=len(entries), skipped=len(msgs) - len(entries))

    def search(
        self,
        query: str,
        limit: int = 10,
        domain: str | None = None,
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
    ) -> list[Memory]:
        """Search memories.

        >>> results = mind.search("exercise")
        >>> results[0].content
        'I like running'
        """
        results = self._mind.search(
            query,
            domain=domain,
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
        )
        habits = self._mind.query_habits(query)

        memories = []
        for r in results[:limit]:
            meta = dict(r.entry.metadata) if r.entry.metadata else {}
            meta["retrieval_method"] = r.method
            memories.append(Memory(
                content=r.entry.content,
                domain=r.entry.domain,
                level=r.entry.level.name.lower(),
                score=r.score,
                id=r.entry.id,
                user_id=r.entry.user_id,
                agent_id=r.entry.agent_id,
                session_id=r.entry.session_id,
                created_at=r.entry.created_at,
                updated_at=r.entry.updated_at,
                metadata=meta,
            ))

        # Skip habits when filtering by user — habits are global
        if not (user_id or agent_id or session_id):
            for h in habits[:3]:
                memories.append(Memory(
                    content=h.description,
                    domain="habits",
                    level="habit",
                    score=h.confidence,
                    metadata={"status": h.status.value},
                ))

        return memories[:limit]

    # --- CRUD ---

    def get(self, memory_id: int) -> Memory | None:
        entry = self._mind.get_memory(memory_id)
        if entry is None:
            return None
        return Memory(
            content=entry.content,
            domain=entry.domain,
            level=entry.level.name.lower(),
            id=entry.id,
            user_id=entry.user_id,
            agent_id=entry.agent_id,
            session_id=entry.session_id,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            metadata=dict(entry.metadata),
        )

    def update(
        self,
        memory_id: int,
        content: str | None = None,
        metadata: dict | None = None,
    ) -> Memory | None:
        entry = self._mind.update_memory(memory_id, content=content, metadata=metadata)
        if entry is None:
            return None
        return self.get(memory_id)

    def delete(self, memory_id: int) -> bool:
        return self._mind.delete_memory(memory_id)

    def delete_all(
        self, user_id: str = "", agent_id: str = "", session_id: str = ""
    ) -> int:
        """Delete all memories matching a scope. At least one filter required
        to prevent accidental wipes."""
        return self._mind.delete_all_memories(
            user_id=user_id, agent_id=agent_id, session_id=session_id
        )

    def history(self, memory_id: int) -> list[dict]:
        return self._mind.memory_history(memory_id)

    def list(
        self,
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
        limit: int = 100,
    ) -> list[Memory]:
        entries = self._mind.list_memories(
            user_id=user_id, agent_id=agent_id, session_id=session_id, limit=limit
        )
        return [
            Memory(
                content=e.content,
                domain=e.domain,
                level=e.level.name.lower(),
                id=e.id,
                user_id=e.user_id,
                agent_id=e.agent_id,
                session_id=e.session_id,
                created_at=e.created_at,
                updated_at=e.updated_at,
                metadata=dict(e.metadata),
            )
            for e in entries
        ]

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
        if not self._mind.is_llm_available():
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
    llm=None,
) -> SimpleRadioMind:
    """One-line connection to RadioMind.

    Args:
        home: Data directory (default: ~/.radiomind).
        config_path: Path to config.toml.
        llm: External LLM callable: (prompt: str, system: str) → str.

    Examples:
        # No LLM — pure memory (add/search/digest work, refine is no-op)
        mind = radiomind.connect()

        # With host framework's LLM
        mind = radiomind.connect(llm=lambda p, s: my_llm.generate(p, system=s))

        # With OpenAI client
        mind = radiomind.connect(llm=lambda p, s: client.chat.completions.create(
            model="gpt-4o", messages=[{"role":"system","content":s},{"role":"user","content":p}]
        ).choices[0].message.content)
    """
    return SimpleRadioMind(home=home, config_path=config_path, llm=llm)
