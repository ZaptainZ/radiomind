"""Chat Refinement — Three-Body Debate (三体博弈).

Inspired by Three Kingdoms: three agents with competing interests
produce more robust insights than two. (ICLR 2025 DMAD: 91% vs 82%)

Roles:
  Guardian (魏) — rewards consistency with existing habits
  Explorer (吴) — rewards novelty and new patterns
  Reducer  (蜀) — rewards parsimony and merging
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from radiomind.core.llm import LLMRouter
from radiomind.core.types import Habit, MemoryEntry, MemoryStatus, RefinementResult
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore

GUARDIAN_SYSTEM = """You are the Guardian (守护者). Your goal is CONSISTENCY.
Evaluate whether the new memories align with existing habits and knowledge.
If they contradict existing habits, flag the contradiction.
If they reinforce existing habits, recommend strengthening.
Be concise. Respond in the user's language."""

EXPLORER_SYSTEM = """You are the Explorer (探索者). Your goal is NOVELTY.
Look for new patterns, unexpected connections, and fresh insights in the memories.
Challenge assumptions. Find what's genuinely new and worth remembering.
Be concise. Respond in the user's language."""

REDUCER_SYSTEM = """You are the Reducer (精简者). Your goal is PARSIMONY.
Determine if memories can be merged, simplified, or eliminated.
Advocate for fewer, more precise memories over many redundant ones.
Be concise. Respond in the user's language."""

DEBATE_PROMPT = """Here are the user's recent memories in the "{domain}" domain:

{memories}

Existing habits:
{habits}

As the {role}, analyze these memories. In 2-3 sentences:
1. State your position
2. Propose a specific action (add/merge/strengthen/remove)"""

SYNTHESIS_PROMPT = """Three analysts debated about user memories in the "{domain}" domain.

Guardian (consistency): {guardian}

Explorer (novelty): {explorer}

Reducer (parsimony): {reducer}

Based on this debate, extract 0-2 new insights worth remembering as habits.
For each insight, output one line in this format:
INSIGHT: <concise habit description>
CONFIDENCE: <0.0-1.0>

If no insight is worth adding, output: NONE"""


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

        for insight in all_insights:
            self._habits.add_habit(
                insight.description,
                concepts=[(insight.description.split()[0], insight.description)],
            )

        return RefinementResult(
            new_insights=all_insights,
            merged=0,
            pruned=0,
            duration_s=time.time() - t0,
            model_used=self._llm.config.get("llm.ollama.model", "unknown"),
            tokens_used=total_tokens,
        )

    def _debate_round(self, domain: str) -> DebateRound:
        result = DebateRound(domain=domain)
        t0 = time.time()

        memories = self._store.list_by_domain(domain, limit=20)
        if not memories:
            return result

        mem_text = "\n".join(f"- {m.content}" for m in memories[:15])
        habit_text = "\n".join(f"- {h.description}" for h in self._habits.all_habits()) or "(none)"

        guardian_model = self._cfg.get("guardian_model", "") or ""
        explorer_model = self._cfg.get("explorer_model", "") or ""
        reducer_model = self._cfg.get("reducer_model", "") or ""

        # Three agents speak
        result.guardian_response = self._speak(
            "Guardian", domain, mem_text, habit_text, GUARDIAN_SYSTEM, guardian_model
        )
        result.explorer_response = self._speak(
            "Explorer", domain, mem_text, habit_text, EXPLORER_SYSTEM, explorer_model
        )
        result.reducer_response = self._speak(
            "Reducer", domain, mem_text, habit_text, REDUCER_SYSTEM, reducer_model
        )

        # Synthesize
        synth_prompt = SYNTHESIS_PROMPT.format(
            domain=domain,
            guardian=result.guardian_response,
            explorer=result.explorer_response,
            reducer=result.reducer_response,
        )
        try:
            resp = self._llm.generate(synth_prompt, system="You extract insights from debates.")
            result.synthesis = resp.text
            result.tokens_used = resp.tokens_prompt + resp.tokens_completion
            result.insights = self._parse_insights(resp.text)
        except Exception as e:
            result.synthesis = f"[synthesis failed: {e}]"

        result.duration_s = time.time() - t0
        return result

    def _speak(
        self, role: str, domain: str, memories: str, habits: str, system: str, model: str
    ) -> str:
        prompt = DEBATE_PROMPT.format(
            domain=domain, memories=memories, habits=habits, role=role
        )
        try:
            resp = self._llm.generate(prompt, system=system, model=model)
            return resp.text.strip()
        except Exception as e:
            return f"[{role} unavailable: {e}]"

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
                confidence = 0.5
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

    def _get_active_domains(self) -> list[str]:
        domains = self._store.list_domains()
        return [d["name"] for d in domains[:5]]
