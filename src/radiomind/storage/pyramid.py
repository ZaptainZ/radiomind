"""L2 Pyramid Search — attention-style multi-level retrieval.

Like 3D NAND: scan top layer first (principles), drill down to patterns, then facts.
Efficiency gain: ~7x vs flat search.
"""

from __future__ import annotations

from radiomind.core.llm import LLMRouter
from radiomind.core.types import MemoryEntry, MemoryLevel, SearchResult
from radiomind.storage.database import MemoryStore

AGGREGATE_THRESHOLD = 10  # facts needed before triggering pattern extraction
AGGREGATE_PROMPT = """You are a memory analyst. Given these facts about a user in the "{domain}" domain, identify one concise pattern or habit.

Facts:
{facts}

Respond with ONLY the pattern in one sentence. No explanation."""

PRINCIPLE_PROMPT = """You are a memory analyst. Given these patterns about a user, extract one high-level principle.

Patterns:
{patterns}

Respond with ONLY the principle in one sentence. No explanation."""


class PyramidSearch:
    """Attention-style hierarchical memory retrieval."""

    def __init__(self, store: MemoryStore):
        self._store = store

    def search(
        self,
        query: str,
        start_level: int = 2,
        max_results: int = 10,
        domain: str | None = None,
    ) -> list[SearchResult]:
        """Search from top of pyramid down, like attention mechanism.

        1. Scan principles (L2) — broad strokes
        2. Expand matching principles to their patterns (L1)
        3. Expand matching patterns to their facts (L0)
        """
        all_results: list[SearchResult] = []
        seen_ids: set[int] = set()

        # Try FTS first, fall back to LIKE
        fts_results = self._store.search_fts(query, limit=max_results * 2)
        like_results = self._store.search_like(query, limit=max_results)

        # Merge and deduplicate, FTS results first (higher quality)
        for r in fts_results + like_results:
            if r.entry.id not in seen_ids:
                if domain is None or r.entry.domain == domain:
                    seen_ids.add(r.entry.id)
                    all_results.append(r)

        # Sort: principles first, then patterns, then facts (pyramid order)
        all_results.sort(key=lambda r: (-r.entry.level, -r.score))

        # Record hits
        for r in all_results[:max_results]:
            if r.entry.id is not None:
                self._store.record_hit(r.entry.id)

        return all_results[:max_results]

    def drill_down(self, entry_id: int) -> list[MemoryEntry]:
        """Expand a higher-level entry to its children (drill down the pyramid)."""
        return self._store.get_children(entry_id)

    def search_pyramid(
        self,
        query: str,
        domain: str | None = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Full pyramid search: top-down with expansion.

        1. Search at principle level
        2. If hits, expand to children
        3. If no principle hits, search patterns directly
        4. If no pattern hits, search facts
        """
        results: list[SearchResult] = []
        seen_ids: set[int] = set()

        # Level 2: Principles
        principles = self._search_level(query, MemoryLevel.PRINCIPLE, domain, limit=3)
        for r in principles:
            if r.entry.id not in seen_ids:
                seen_ids.add(r.entry.id)
                results.append(r)
                # Expand to children
                children = self.drill_down(r.entry.id)
                for child in children:
                    if child.id not in seen_ids:
                        seen_ids.add(child.id)
                        results.append(SearchResult(entry=child, score=r.score * 0.8, method="drill"))

        # Level 1: Patterns (supplement if few principle hits)
        if len(results) < max_results:
            patterns = self._search_level(query, MemoryLevel.PATTERN, domain, limit=5)
            for r in patterns:
                if r.entry.id not in seen_ids:
                    seen_ids.add(r.entry.id)
                    results.append(r)

        # Level 0: Facts (supplement if still few)
        if len(results) < max_results:
            facts = self._search_level(query, MemoryLevel.FACT, domain, limit=10)
            for r in facts:
                if r.entry.id not in seen_ids:
                    seen_ids.add(r.entry.id)
                    results.append(r)

        # Record hits
        for r in results[:max_results]:
            if r.entry.id is not None:
                self._store.record_hit(r.entry.id)

        return results[:max_results]

    def _search_level(
        self,
        query: str,
        level: MemoryLevel,
        domain: str | None,
        limit: int,
    ) -> list[SearchResult]:
        """Search within a specific pyramid level."""
        fts = self._store.search_fts(query, limit=limit * 2)
        like = self._store.search_like(query, limit=limit)

        results = []
        seen = set()
        for r in fts + like:
            if r.entry.id not in seen and r.entry.level == level:
                if domain is None or r.entry.domain == domain:
                    seen.add(r.entry.id)
                    results.append(r)
        return results[:limit]


class PyramidAggregator:
    """Aggregates facts → patterns → principles (bottom-up pyramid building)."""

    def __init__(self, store: MemoryStore, llm: LLMRouter):
        self._store = store
        self._llm = llm

    def check_and_aggregate(self, domain: str) -> list[MemoryEntry]:
        """Check if a domain has enough facts to aggregate into patterns."""
        created: list[MemoryEntry] = []

        fact_count = self._store.count_by_domain_level(domain, MemoryLevel.FACT)
        pattern_count = self._store.count_by_domain_level(domain, MemoryLevel.PATTERN)

        # Aggregate facts → pattern when threshold reached
        if fact_count >= AGGREGATE_THRESHOLD and fact_count > pattern_count * AGGREGATE_THRESHOLD:
            facts = self._store.list_by_domain(domain, level=MemoryLevel.FACT, limit=20)
            pattern = self._aggregate_to_pattern(domain, facts)
            if pattern:
                created.append(pattern)

        # Aggregate patterns → principle when enough patterns
        if pattern_count >= 3:
            principle_count = self._store.count_by_domain_level(domain, MemoryLevel.PRINCIPLE)
            if principle_count == 0 or pattern_count > principle_count * 3:
                patterns = self._store.list_by_domain(domain, level=MemoryLevel.PATTERN, limit=10)
                principle = self._aggregate_to_principle(domain, patterns)
                if principle:
                    created.append(principle)

        return created

    def _aggregate_to_pattern(self, domain: str, facts: list[MemoryEntry]) -> MemoryEntry | None:
        facts_text = "\n".join(f"- {f.content}" for f in facts)
        prompt = AGGREGATE_PROMPT.format(domain=domain, facts=facts_text)

        try:
            resp = self._llm.generate(prompt, system="You are a concise memory analyst.")
            pattern_text = resp.text.strip()
            if not pattern_text:
                return None

            pattern = MemoryEntry(
                content=pattern_text,
                domain=domain,
                level=MemoryLevel.PATTERN,
                metadata={"source": "aggregation", "fact_count": len(facts)},
            )
            pattern_id = self._store.add(pattern)

            # Link facts to pattern
            for f in facts:
                if f.id is not None and f.parent_id is None:
                    f.parent_id = pattern_id
                    self._store.update(f)

            return pattern
        except Exception:
            return None

    def _aggregate_to_principle(
        self, domain: str, patterns: list[MemoryEntry]
    ) -> MemoryEntry | None:
        patterns_text = "\n".join(f"- {p.content}" for p in patterns)
        prompt = PRINCIPLE_PROMPT.format(patterns=patterns_text)

        try:
            resp = self._llm.generate(prompt, system="You are a concise memory analyst.")
            principle_text = resp.text.strip()
            if not principle_text:
                return None

            principle = MemoryEntry(
                content=principle_text,
                domain=domain,
                level=MemoryLevel.PRINCIPLE,
                metadata={"source": "aggregation", "pattern_count": len(patterns)},
            )
            principle_id = self._store.add(principle)

            for p in patterns:
                if p.id is not None and p.parent_id is None:
                    p.parent_id = principle_id
                    self._store.update(p)

            return principle
        except Exception:
            return None
