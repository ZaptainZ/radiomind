"""Step-by-step refinement — let the host AI do the thinking.

Instead of RadioMind calling its own LLM internally (黑盒 mode),
this module breaks refinement into steps that the host AI executes:

  RadioMind = organizer (provides prompts, collects results)
  Host AI   = thinker (does the actual reasoning)

This means:
  - Zero extra LLM cost (host AI is already running)
  - Higher quality reasoning (Claude/GPT >> qwen-turbo)
  - Works in CC/Codex where RadioMind can't access the internal LLM

Usage (MCP / CLI):
  step1 = refine_step("prepare", domain="health")
  step2 = refine_step("guardian", response="...")
  step3 = refine_step("explorer", response="...")
  step4 = refine_step("reducer", response="...")
  # RadioMind auto-synthesizes and writes to L3
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from radiomind.core.types import Habit, MemoryEntry, MemoryLevel, MemoryStatus
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore

GUARDIAN_PROMPT = """You are the Guardian (守护者). Your goal is CONSISTENCY.

Here are the user's recent memories in the "{domain}" domain:
{memories}

Existing habits:
{habits}

Evaluate: do these memories align with existing habits?
In 2-3 sentences: state your position and propose an action (strengthen/flag contradiction)."""

EXPLORER_PROMPT = """You are the Explorer (探索者). Your goal is NOVELTY.

Memories in "{domain}":
{memories}

Existing habits:
{habits}

The Guardian said: {guardian_response}

Look for new patterns or unexpected connections. Challenge the Guardian if needed.
In 2-3 sentences: state what's genuinely new and worth remembering."""

REDUCER_PROMPT = """You are the Reducer (精简者). Your goal is PARSIMONY.

Memories in "{domain}":
{memories}

Guardian's view: {guardian_response}
Explorer's view: {explorer_response}

Can any memories be merged or eliminated? Advocate for fewer, more precise memories.
In 2-3 sentences: propose specific merges or removals."""

SYNTHESIS_PROMPT = """Three analysts debated about memories in the "{domain}" domain.

Guardian (consistency): {guardian_response}
Explorer (novelty): {explorer_response}
Reducer (parsimony): {reducer_response}

Extract 0-2 new insights worth remembering as habits.
For each insight, output:
INSIGHT: <concise habit description>
CONFIDENCE: <0.0-1.0>

If nothing is worth adding, output: NONE"""

DREAM_PRUNE_PROMPT = """Review these memories for pruning:

{memories}

Identify:
1. REDUNDANT pairs that should be merged (output: MERGE: <id_a> + <id_b> → <merged text>)
2. CONTRADICTIONS to resolve (output: KEEP: <id> ARCHIVE: <id> REASON: <why>)
3. STALE memories that haven't been useful (output: DECAY: <id>)

If nothing needs pruning, output: NONE"""

DREAM_WANDER_PROMPT = """Here are {n} seemingly unrelated memories from different domains:

{items}

As a free-thinking mind, find a hidden connection or meta-pattern.
If you find a genuine insight, respond:
INSIGHT: <the meta-pattern in one sentence>
CONFIDENCE: <0.0-1.0>

If nothing connects, respond: NONE"""


@dataclass
class StepResult:
    """Result of a single refinement step."""
    step: str
    done: bool = False
    prompt: str = ""
    context: str = ""
    next_step: str = ""
    insights: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    session_data: dict = field(default_factory=dict)


class StepRefiner:
    """Stateful step-by-step refinement engine.

    Each domain gets its own session. The host AI calls steps sequentially.
    """

    def __init__(self, store: MemoryStore, habits: HabitStore):
        self._store = store
        self._habits = habits
        self._sessions: dict[str, dict] = {}

    def step(self, step_name: str, domain: str = "", response: str = "", session_id: str = "") -> StepResult:
        """Execute a refinement step.

        Args:
            step_name: prepare/guardian/explorer/reducer/synthesize/dream_prune/dream_wander
            domain: target domain (required for prepare)
            response: host AI's response to the previous step's prompt
            session_id: session key (auto-generated from domain if empty)
        """
        if session_id:
            sid = session_id
        elif domain:
            sid = f"refine_{domain}"
        elif self._sessions:
            sid = next(iter(self._sessions))
        else:
            sid = "refine_default"

        if step_name == "prepare":
            return self._prepare(domain, sid)
        elif step_name == "guardian":
            return self._guardian(sid, response)
        elif step_name == "explorer":
            return self._explorer(sid, response)
        elif step_name == "reducer":
            return self._reducer(sid, response)
        elif step_name == "synthesize":
            return self._synthesize(sid, response)
        elif step_name == "dream_prune":
            return self._dream_prune(domain, sid)
        elif step_name == "dream_wander":
            return self._dream_wander(sid)
        elif step_name == "dream_apply":
            return self._dream_apply(sid, response)
        else:
            return StepResult(step=step_name, done=True, context=f"Unknown step: {step_name}")

    # --- Chat Refinement Steps ---

    def _prepare(self, domain: str, sid: str) -> StepResult:
        """Prepare debate materials for a domain."""
        if not domain:
            domains = self._store.list_domains()
            if domains:
                domain = domains[0]["name"]
            else:
                return StepResult(step="prepare", done=True, context="No memories to refine.")

        memories = self._store.list_by_domain(domain, limit=15)
        if not memories:
            return StepResult(step="prepare", done=True, context=f"No memories in domain '{domain}'.")

        mem_text = "\n".join(f"- [{m.id}] {m.content}" for m in memories)
        habit_text = "\n".join(f"- {h.description}" for h in self._habits.all_habits()) or "(none yet)"

        self._sessions[sid] = {
            "domain": domain,
            "memories": mem_text,
            "habits": habit_text,
            "guardian": "",
            "explorer": "",
            "reducer": "",
            "started_at": time.time(),
        }

        prompt = GUARDIAN_PROMPT.format(domain=domain, memories=mem_text, habits=habit_text)

        return StepResult(
            step="prepare",
            next_step="guardian",
            prompt=prompt,
            context=f"Debate prepared for domain '{domain}' with {len(memories)} memories.",
            session_data={"domain": domain, "memory_count": len(memories)},
        )

    def _guardian(self, sid: str, response: str) -> StepResult:
        """Record guardian's response, prepare explorer's prompt."""
        session = self._sessions.get(sid, {})
        session["guardian"] = response

        prompt = EXPLORER_PROMPT.format(
            domain=session.get("domain", ""),
            memories=session.get("memories", ""),
            habits=session.get("habits", ""),
            guardian_response=response,
        )

        return StepResult(
            step="guardian",
            next_step="explorer",
            prompt=prompt,
            context=f"Guardian responded. Now the Explorer's turn.",
        )

    def _explorer(self, sid: str, response: str) -> StepResult:
        """Record explorer's response, prepare reducer's prompt."""
        session = self._sessions.get(sid, {})
        session["explorer"] = response

        prompt = REDUCER_PROMPT.format(
            domain=session.get("domain", ""),
            memories=session.get("memories", ""),
            guardian_response=session.get("guardian", ""),
            explorer_response=response,
        )

        return StepResult(
            step="explorer",
            next_step="reducer",
            prompt=prompt,
            context="Explorer responded. Now the Reducer's turn.",
        )

    def _reducer(self, sid: str, response: str) -> StepResult:
        """Record reducer's response, prepare synthesis prompt."""
        session = self._sessions.get(sid, {})
        session["reducer"] = response

        prompt = SYNTHESIS_PROMPT.format(
            domain=session.get("domain", ""),
            guardian_response=session.get("guardian", ""),
            explorer_response=session.get("explorer", ""),
            reducer_response=response,
        )

        return StepResult(
            step="reducer",
            next_step="synthesize",
            prompt=prompt,
            context="All three debaters have spoken. Now synthesize insights.",
        )

    def _synthesize(self, sid: str, response: str) -> StepResult:
        """Parse synthesis response and write insights to L3."""
        session = self._sessions.get(sid, {})
        insights = self._parse_insights(response)

        for insight in insights:
            self._habits.add_habit(
                insight["description"],
                concepts=[(insight["description"].split()[0], insight["description"])],
            )

        duration = time.time() - session.get("started_at", time.time())
        del self._sessions[sid]

        return StepResult(
            step="synthesize",
            done=True,
            insights=insights,
            context=f"Debate complete. {len(insights)} insights written to L3 habits.",
            session_data={"duration_s": round(duration, 1), "domain": session.get("domain", "")},
        )

    # --- Dream Steps ---

    def _dream_prune(self, domain: str, sid: str) -> StepResult:
        """Prepare pruning prompt with candidate memories."""
        facts = []
        if domain:
            facts = self._store.list_by_domain(domain, level=MemoryLevel.FACT, limit=30)
        else:
            for d in self._store.list_domains()[:5]:
                facts.extend(self._store.list_by_domain(d["name"], level=MemoryLevel.FACT, limit=10))

        if not facts:
            return StepResult(step="dream_prune", done=True, context="No memories to prune.")

        mem_text = "\n".join(f"- [id={m.id}] (hits={m.hit_count}, domain={m.domain}) {m.content}" for m in facts)

        self._sessions[sid] = {"prune_memories": facts}

        return StepResult(
            step="dream_prune",
            next_step="dream_apply",
            prompt=DREAM_PRUNE_PROMPT.format(memories=mem_text),
            context=f"Prepared {len(facts)} memories for pruning review.",
        )

    def _dream_wander(self, sid: str) -> StepResult:
        """Prepare wandering prompt with random cross-domain items."""
        import random

        candidates = []
        for h in self._habits.all_habits():
            candidates.append(f"[habit] {h.description}")
        for p in self._store.list_by_level(MemoryLevel.PRINCIPLE, limit=10):
            candidates.append(f"[principle/{p.domain}] {p.content}")
        for p in self._store.list_by_level(MemoryLevel.PATTERN, limit=15):
            candidates.append(f"[pattern/{p.domain}] {p.content}")

        if len(candidates) < 3:
            return StepResult(step="dream_wander", done=True, context="Not enough memories for wandering.")

        sample = random.sample(candidates, min(5, len(candidates)))
        items_text = "\n".join(f"{i+1}. {item}" for i, item in enumerate(sample))

        return StepResult(
            step="dream_wander",
            next_step="dream_apply",
            prompt=DREAM_WANDER_PROMPT.format(n=len(sample), items=items_text),
            context=f"Randomly sampled {len(sample)} items for free association.",
        )

    def _dream_apply(self, sid: str, response: str) -> StepResult:
        """Apply pruning/wandering results."""
        actions = []

        # Parse MERGE/KEEP/ARCHIVE/DECAY/INSIGHT from response
        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("MERGE:"):
                actions.append({"type": "merge", "detail": line[6:].strip()})
            elif line.startswith("KEEP:"):
                actions.append({"type": "keep", "detail": line[5:].strip()})
            elif line.startswith("ARCHIVE:"):
                detail = line[8:].strip()
                try:
                    mid = int(detail.split()[0])
                    self._store.archive(mid)
                    actions.append({"type": "archive", "id": mid})
                except (ValueError, IndexError):
                    pass
            elif line.startswith("DECAY:"):
                detail = line[6:].strip()
                try:
                    mid = int(detail.split()[0])
                    self._store.increment_decay(mid)
                    actions.append({"type": "decay", "id": mid})
                except (ValueError, IndexError):
                    pass
            elif line.startswith("INSIGHT:"):
                desc = line[8:].strip()
                if desc:
                    self._habits.add_habit(desc, concepts=[(desc.split()[0], desc)])
                    actions.append({"type": "insight", "description": desc})

        self._sessions.pop(sid, None)

        return StepResult(
            step="dream_apply",
            done=True,
            actions=actions,
            context=f"Applied {len(actions)} dream actions.",
        )

    # --- Helpers ---

    @staticmethod
    def _parse_insights(text: str) -> list[dict]:
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
                if i + 1 < len(lines) and lines[i+1].strip().upper().startswith("CONFIDENCE:"):
                    try:
                        confidence = float(lines[i+1].strip().split(":")[-1].strip())
                    except ValueError:
                        pass
                    i += 1
                if desc:
                    insights.append({"description": desc, "confidence": min(max(confidence, 0.0), 1.0)})
            i += 1
        return insights

    def active_sessions(self) -> list[str]:
        return list(self._sessions.keys())
