"""Chat Refinement — habit mining via trinity.

Three-way debate is the primitive. The three opposing stances here are
natural tensions of habit mining: consistency (what aligns with existing
habits?) vs novelty (unexpected patterns?) vs parsimony (merge-redundant).
The LLM picks and labels those stances per-call; we don't hardcode role
names.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from radiomind.core.llm import LLMRouter
from radiomind.core.types import Habit, MemoryEntry, MemoryStatus, RefinementResult
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore


@dataclass
class DebateRound:
    domain: str
    guardian_response: str = ""
    explorer_response: str = ""
    reducer_response: str = ""
    synthesis: str = ""
    insights: list[Habit] = field(default_factory=list)
    tokens_used: int = 0
    duration_s: float = 0.0


class ChatRefinement:
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

    def refine(self, domain: str | None = None) -> RefinementResult:
        t0 = time.time()
        total_tokens = 0
        all_insights: list[Habit] = []

        domains = [domain] if domain else self._get_active_domains()

        for dom in domains:
            round_result = self._debate_round(dom)
            all_insights.extend(round_result.insights)
            total_tokens += round_result.tokens_used

        accepted: list[Habit] = []
        for insight in all_insights:
            h = self._habits.add_habit(
                insight.description,
                concepts=[(insight.description.split()[0], insight.description)],
                confidence=insight.confidence,
                evidence=insight.evidence,
                falsifier=insight.falsifier,
            )
            if h is not None:
                accepted.append(insight)
        all_insights = accepted

        return RefinementResult(
            new_insights=all_insights,
            merged=0,
            pruned=0,
            duration_s=time.time() - t0,
            model_used=self._resolve_model_used(),
            tokens_used=total_tokens,
        )

    def _resolve_model_used(self) -> str:
        """Return the actually-used default model regardless of backend.

        Earlier versions hardcoded the ollama key which misreported the
        model when the user had configured OpenAI-compatible backends
        (Dashscope/Qwen, DeepSeek, etc.).
        """
        backend = self._llm.config.get("llm.default_backend", "")
        by_backend = self._llm.config.get(f"llm.{backend}.model", "") if backend else ""
        if by_backend:
            return by_backend
        return self._llm.config.get("llm.ollama.model", "unknown")

    def _debate_round(self, domain: str) -> DebateRound:
        """Mine habits from a domain via trinity.debate() — single LLM call."""
        from radiomind.refinement.trinity import debate

        result = DebateRound(domain=domain)
        t0 = time.time()

        memories = self._store.list_by_domain(domain, limit=80)
        if not memories:
            return result

        mem_text = "\n".join(f"- {m.content}" for m in memories[:60])
        habit_text = "\n".join(
            f"- {h.description}" for h in self._habits.all_habits()
        ) or "(none)"

        debate_result = debate(
            task=(
                f"Mine 0-2 durable habit insights about the user from the "
                f"memories in the '{domain}' domain. Tensions: consistency "
                f"(what reinforces existing habits?) vs novelty (patterns "
                f"not yet captured?) vs parsimony (merge-redundant / "
                f"simplest explanation).\n"
                f"Existing habits:\n{habit_text}\n"
                f"Each insight MUST have evidence (cite memory text) and "
                f"a falsifier (what future memory would invalidate it). "
                f"Output [] when nothing durable emerges."
            ),
            evidence=mem_text,
            llm=self._llm,
            extra_schema=(
                '  "insights": [{"description": str, "confidence": float, '
                '"evidence": str, "falsifier": str}]'
            ),
        )
        result.duration_s = time.time() - t0
        if not debate_result:
            result.synthesis = "[debate returned nothing]"
            return result

        result.synthesis = str(debate_result.get("final_answer") or "")
        insights_raw = debate_result.get("insights") or []
        if not isinstance(insights_raw, list):
            insights_raw = []
        parsed: list[Habit] = []
        for item in insights_raw:
            if not isinstance(item, dict):
                continue
            desc = str(item.get("description") or "").strip()
            if not desc:
                continue
            try:
                conf = float(item.get("confidence") or 0.5)
            except (TypeError, ValueError):
                conf = 0.5
            parsed.append(Habit(
                description=desc,
                status=MemoryStatus.CANDIDATE,
                confidence=min(max(conf, 0.0), 1.0),
                evidence=str(item.get("evidence") or "")[:300],
                falsifier=str(item.get("falsifier") or "")[:200],
            ))
        result.insights = parsed
        return result

    def _get_active_domains(self) -> list[str]:
        domains = self._store.list_domains()
        return [d["name"] for d in domains[:5]]
