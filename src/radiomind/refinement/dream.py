"""Dream Refinement — Pruning + Wandering (做梦炼化).

Phase 1: Pruning (SHY — Synaptic Homeostasis Hypothesis)
  - Contradictions → resolve
  - Redundancy → merge
  - Unused → decay → archive

Phase 2: Wandering (DMN — Default Mode Network)
  - Random associations → discover hidden cross-domain meta-patterns

Phase 3: Dream Journal
  - Record what was pruned and what was discovered
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from radiomind.core.llm import LLMRouter
from radiomind.core.types import Habit, MemoryEntry, MemoryLevel, MemoryStatus, RefinementResult
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore

MERGE_PROMPT = """These two memories seem redundant or overlapping:
1. {mem_a}
2. {mem_b}

Merge them into a single, more precise memory.
Respond with ONLY the merged text, nothing else."""

CONTRADICTION_PROMPT = """These two memories seem to contradict each other:
1. {mem_a} (created: {time_a})
2. {mem_b} (created: {time_b})

Which one should we keep? Consider recency and specificity.
Respond with ONLY "1" or "2" and a brief reason."""

WANDER_PROMPT = """Here are {n} seemingly unrelated habits/memories from different domains:

{items}

As a free-thinking mind wandering during sleep, find a hidden connection
or meta-pattern that links some or all of these items.

If you find a genuine insight, respond:
INSIGHT: <the meta-pattern in one sentence>
CONFIDENCE: <0.0-1.0>

If nothing connects, respond: NONE"""


@dataclass
class DreamJournal:
    merged: list[tuple[str, str, str]] = field(default_factory=list)  # (a, b, merged)
    pruned: list[str] = field(default_factory=list)
    decayed: list[str] = field(default_factory=list)
    wanderings: list[str] = field(default_factory=list)
    insights: list[Habit] = field(default_factory=list)


class DreamRefinement:
    def __init__(
        self,
        store: MemoryStore,
        habits: HabitStore,
        llm: LLMRouter,
        config: dict | None = None,
    ):
        self._store = store
        self._habits = habits
        self._llm = llm
        self._cfg = config or {}
        self._decay_days = self._cfg.get("decay_days", 30)
        self._decay_threshold = self._cfg.get("decay_threshold", 3)
        self._wander_size = self._cfg.get("wander_sample_size", 5)

    def dream(self) -> RefinementResult:
        t0 = time.time()
        journal = DreamJournal()

        # Phase 1: Pruning
        self._prune_decay(journal)
        self._prune_redundancy(journal)

        # Phase 2: Wandering
        self._wander(journal)

        # Write wandering insights to L3
        for insight in journal.insights:
            self._habits.add_habit(
                insight.description,
                concepts=[(insight.description.split()[0], insight.description)],
            )

        return RefinementResult(
            new_insights=journal.insights,
            merged=len(journal.merged),
            pruned=len(journal.pruned) + len(journal.decayed),
            duration_s=time.time() - t0,
            model_used=self._llm.config.get("llm.ollama.model", "unknown"),
            tokens_used=0,
        )

    # --- Phase 1: Pruning ---

    def _prune_decay(self, journal: DreamJournal) -> None:
        """Mark old unused memories for decay, archive heavily decayed ones."""
        cutoff = time.time() - self._decay_days * 86400
        stats = self._store.stats()

        for domain_info in stats.get("domains", []):
            domain = domain_info["name"]
            facts = self._store.list_by_domain(domain, level=MemoryLevel.FACT, limit=100)
            for fact in facts:
                should_decay = False
                if fact.last_hit_at > 0 and fact.last_hit_at < cutoff:
                    should_decay = True
                elif fact.hit_count == 0 and fact.created_at < cutoff:
                    should_decay = True

                if should_decay:
                    self._store.increment_decay(fact.id)
                    fact.decay_count += 1

                    if fact.decay_count >= self._decay_threshold:
                        self._store.archive(fact.id)
                        journal.decayed.append(fact.content)

    def _prune_redundancy(self, journal: DreamJournal) -> None:
        """Find and merge redundant memories within each domain."""
        domains = self._store.list_domains()
        for domain_info in domains[:5]:
            domain = domain_info["name"]
            facts = self._store.list_by_domain(domain, level=MemoryLevel.FACT, limit=30)
            if len(facts) < 2:
                continue

            # Simple pairwise check on recent facts (limit scope)
            checked = set()
            for i, a in enumerate(facts[:10]):
                for b in facts[i + 1 : i + 4]:
                    pair = (min(a.id, b.id), max(a.id, b.id))
                    if pair in checked:
                        continue
                    checked.add(pair)

                    if self._are_similar_text(a.content, b.content):
                        merged = self._merge_pair(a, b)
                        if merged:
                            journal.merged.append((a.content, b.content, merged))

    def _are_similar_text(self, a: str, b: str) -> bool:
        """Quick text similarity check (word overlap ratio)."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return False
        overlap = len(words_a & words_b)
        smaller = min(len(words_a), len(words_b))
        return overlap / smaller > 0.6 if smaller > 0 else False

    def _merge_pair(self, a: MemoryEntry, b: MemoryEntry) -> str | None:
        try:
            prompt = MERGE_PROMPT.format(mem_a=a.content, mem_b=b.content)
            resp = self._llm.generate(prompt, system="You merge memories concisely.")
            merged_text = resp.text.strip()
            if not merged_text:
                return None

            a.content = merged_text
            a.hit_count = max(a.hit_count, b.hit_count)
            self._store.update(a)
            self._store.archive(b.id)
            return merged_text
        except Exception:
            return None

    # --- Phase 2: Wandering ---

    def _wander(self, journal: DreamJournal) -> None:
        """DMN-style free association across domains."""
        all_habits = self._habits.all_habits()
        all_principles = self._store.list_by_level(MemoryLevel.PRINCIPLE, limit=20)
        all_patterns = self._store.list_by_level(MemoryLevel.PATTERN, limit=20)

        candidates = []
        for h in all_habits:
            candidates.append(f"[habit] {h.description}")
        for p in all_principles:
            candidates.append(f"[principle/{p.domain}] {p.content}")
        for p in all_patterns:
            candidates.append(f"[pattern/{p.domain}] {p.content}")

        if len(candidates) < 3:
            return

        sample_size = min(self._wander_size, len(candidates))
        sample = random.sample(candidates, sample_size)

        items_text = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(sample))
        prompt = WANDER_PROMPT.format(n=sample_size, items=items_text)

        try:
            resp = self._llm.generate(prompt, system="You are a creative, free-thinking mind.")
            journal.wanderings.append(resp.text.strip())

            insights = self._parse_insights(resp.text)
            journal.insights.extend(insights)
        except Exception:
            pass

    def _parse_insights(self, text: str) -> list[Habit]:
        if "NONE" in text.upper():
            return []

        insights = []
        lines = text.strip().split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.upper().startswith("INSIGHT:"):
                desc = line[len("INSIGHT:"):].strip()
                confidence = 0.4  # wandering insights start lower
                if i + 1 < len(lines) and lines[i + 1].strip().upper().startswith("CONFIDENCE:"):
                    try:
                        confidence = float(lines[i + 1].strip().split(":")[-1].strip())
                    except ValueError:
                        pass
                    i += 1
                if desc:
                    insights.append(Habit(
                        description=desc,
                        status=MemoryStatus.CANDIDATE,
                        confidence=min(max(confidence, 0.0), 1.0),
                    ))
            i += 1
        return insights
