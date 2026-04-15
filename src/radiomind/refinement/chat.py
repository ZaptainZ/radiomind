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
Flag contradictions. Reinforce what fits.
Every claim you make MUST cite evidence from the listed memories.
Respond in the user's language, concisely."""

EXPLORER_SYSTEM = """You are the Explorer (探索者). Your goal is NOVELTY.
Find patterns, unexpected connections, fresh insights.
Every claim you make MUST cite evidence from the listed memories.
Respond in the user's language, concisely."""

REDUCER_SYSTEM = """You are the Reducer (精简者). Your goal is PARSIMONY.
Identify redundancy; argue for merging or removing.
Every claim you make MUST cite evidence from the listed memories.
Respond in the user's language, concisely."""

DEBATE_PROMPT = """Here are the user's recent memories in the "{domain}" domain:

{memories}

Existing habits:
{habits}

As the {role}, analyze these memories using this exact structure:

POSITION: <one-sentence stance>
EVIDENCE: <reference specific memory lines or habits that support your position>
ACTION: <add | strengthen | merge | remove — one concrete recommendation>
FALSIFIER: <what future memory would prove your position wrong>

Keep it tight."""

SYNTHESIS_PROMPT = """Three analysts debated about user memories in the "{domain}" domain.

Guardian (consistency): {guardian}

Explorer (novelty): {explorer}

Reducer (parsimony): {reducer}

Extract 0-2 new insights worth remembering as habits. Each insight MUST have
grounding in the evidence the debaters cited AND a condition that would
disprove it (so we can re-evaluate later).

Format EXACTLY:
INSIGHT: <concise habit description>
CONFIDENCE: <0.0-1.0>
EVIDENCE: <which cited memories back this up>
FALSIFIER: <future observation that would invalidate it>

If nothing is worth adding, output: NONE"""


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
        guardian_backend = self._cfg.get("guardian_backend", "") or ""
        explorer_backend = self._cfg.get("explorer_backend", "") or ""
        reducer_backend = self._cfg.get("reducer_backend", "") or ""

        # Three agents speak — each can use a different model AND backend
        # so e.g. a cheap local model plays Guardian (cost-sensitive default
        # stance) while a stronger cloud model plays Explorer.
        result.guardian_response = self._speak(
            "Guardian", domain, mem_text, habit_text, GUARDIAN_SYSTEM,
            guardian_model, guardian_backend,
        )
        result.explorer_response = self._speak(
            "Explorer", domain, mem_text, habit_text, EXPLORER_SYSTEM,
            explorer_model, explorer_backend,
        )
        result.reducer_response = self._speak(
            "Reducer", domain, mem_text, habit_text, REDUCER_SYSTEM,
            reducer_model, reducer_backend,
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
        self, role: str, domain: str, memories: str, habits: str,
        system: str, model: str, backend: str = "",
    ) -> str:
        prompt = DEBATE_PROMPT.format(
            domain=domain, memories=memories, habits=habits, role=role
        )
        try:
            resp = self._llm.generate(prompt, system=system, model=model, backend=backend)
            return resp.text.strip()
        except Exception as e:
            return f"[{role} unavailable: {e}]"

    def _parse_insights(self, text: str) -> list[Habit]:
        if text.strip().upper().startswith("NONE") or "\nNONE" in text.upper():
            return []

        insights = []
        lines = text.strip().split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.upper().startswith("INSIGHT:"):
                desc = line[len("INSIGHT:"):].strip()
                confidence = 0.5
                evidence = ""
                falsifier = ""
                # Look ahead up to 4 lines for attribute fields
                j = i + 1
                while j < len(lines) and j <= i + 4:
                    up = lines[j].strip()
                    up_upper = up.upper()
                    if up_upper.startswith("CONFIDENCE:"):
                        try:
                            confidence = float(up.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif up_upper.startswith("EVIDENCE:"):
                        evidence = up.split(":", 1)[1].strip()
                    elif up_upper.startswith("FALSIFIER:"):
                        falsifier = up.split(":", 1)[1].strip()
                    elif up_upper.startswith("INSIGHT:"):
                        break
                    j += 1
                i = j - 1
                if desc:
                    insights.append(Habit(
                        description=desc,
                        status=MemoryStatus.CANDIDATE,
                        confidence=min(max(confidence, 0.0), 1.0),
                        evidence=evidence,
                        falsifier=falsifier,
                    ))
            i += 1
        return insights

    def _get_active_domains(self) -> list[str]:
        domains = self._store.list_domains()
        return [d["name"] for d in domains[:5]]
