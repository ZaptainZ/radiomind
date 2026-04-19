"""On-demand three-body salvage — the answer-side safety net.

Completes the "三体 + 注意力 everywhere" doctrine. Current pipeline:
  ingest → three-body refinement (✓ done)
  aggregate → three-body aggregator (✓ done, upward)
  retrieve → attention-aware level routing (✓ done, downward)
  answer → (vanilla LLM call)
         ↑ THIS LAYER was still a single-shot black box. If the answer
           model abstains ("information not enough"), we accept the loss.

This module adds the missing final layer: when the answer layer
abstains on a question where retrieval DID return plausible evidence,
trigger a focused three-body debate to salvage a best-guess.

- Guardian: lists what the evidence DOES support explicitly
- Explorer: considers what plausible inference is unlocked by the
  evidence even if nothing states it verbatim
- Reducer: picks the best-guess answer + confidence, or confirms that
  true abstention is warranted

Output replaces the original answer when Reducer delivers a commit;
otherwise keeps the abstention (true "we don't know"). No new ingest,
no new storage — this is a query-time safety net only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from radiomind.core.types import SearchResult


# Phrases indicating the answer model abstained. These are the triggers
# for salvage — if the answer contains any of these, we consider running
# trinity fallback. Conservative list: we want to salvage "I don't know"
# but NOT "this is not X" (genuine contradictions).
_ABSTAIN_PATTERNS = (
    "information is not enough",
    "information provided is not enough",
    "not enough information",
    "does not specify",
    "does not say",
    "no information",
    "is not mentioned",
    "is not named",
    "is not stated",
    "no mention of",
    "not specified",
    "cannot determine",
    "can't determine",
    "cannot tell",
    "unable to determine",
    "don't have this information",
    "do not have",
    "memories do not",
    "memories don't",
    "信息不足",
    "不够信息",
    "未提及",
    "没有提到",
    "无法确定",
    "没有信息",
)


def looks_abstained(answer: str) -> bool:
    if not answer:
        return False
    low = answer.lower()
    return any(p in low for p in _ABSTAIN_PATTERNS)


_SALVAGE_GUARDIAN = """You are the Guardian. The answer model just abstained on this question:
Q: {question}

Retrieved memories (what we have):
{memories}

Task: list ONLY what the memories EXPLICITLY support about this question. Do NOT guess. Cite the turn_id for each claim.

Output JSON: {{"explicit_claims": [{{"claim": "...", "from": "turn_id"}}, ...], "strongest_signal": "..."}}"""

_SALVAGE_EXPLORER = """You are the Explorer. The answer model just abstained on this question:
Q: {question}

Retrieved memories:
{memories}

Task: find the BEST plausible inference. Loosen the bar — if a memory nearly answers the question, propose the answer that fits even if not stated verbatim. Consider patterns, lifestyle signals, world knowledge, default assumptions.

Output JSON: {{"plausible_answers": [{{"answer": "...", "reason": "...", "confidence": 0.6}}, ...]}}

Include up to 3 candidates, sorted by confidence."""

_SALVAGE_REDUCER = """You are the Reducer. The answer model abstained on:
Q: {question}

Guardian's explicit claims:
{guardian}

Explorer's plausible inferences:
{explorer}

Decide: is this a case for committing to a best-guess, or is true abstention warranted?

Rules:
- If Guardian has explicit claims that actually answer the question → commit to that answer.
- If Explorer's top inference has confidence >= 0.6 AND is supported by at least 2 pieces of evidence → commit.
- If the question is truly unanswerable from the memories → keep abstention.
- For questions asking "what might / what could / who likely" → it's an inference question and strong Explorer candidate should commit.

Output JSON:
{{"decision": "commit"|"abstain", "answer": "<final answer text if commit, else empty>", "reason": "<one sentence>", "confidence": 0-1}}"""


@dataclass
class SalvageResult:
    committed: bool
    answer: str
    reason: str
    confidence: float


class AbstentionSalvager:
    """Query-time trinity fallback for answer-layer abstentions.

    Sits AFTER the answer LLM call — if the answer is an abstention AND
    retrieval returned evidence, this fires a 3-call trinity debate to
    produce a best-guess answer.
    """

    def __init__(self, llm_fn: Callable[[str, str], str]):
        """llm_fn: (prompt, system) → response text."""
        self._llm = llm_fn

    def salvage(
        self,
        question: str,
        answer: str,
        retrieved: list[SearchResult],
        max_mem_lines: int = 40,
    ) -> SalvageResult | None:
        """Return salvaged answer if trinity commits, else None to preserve original."""
        if not looks_abstained(answer):
            return None
        if not retrieved:
            return None

        mem_text = self._format_memories(retrieved[:max_mem_lines])

        # Parallel Guardian + Explorer
        from concurrent.futures import ThreadPoolExecutor
        g_prompt = _SALVAGE_GUARDIAN.format(question=question, memories=mem_text)
        e_prompt = _SALVAGE_EXPLORER.format(question=question, memories=mem_text)
        with ThreadPoolExecutor(max_workers=2) as ex:
            g_fut = ex.submit(self._call, g_prompt, "Guardian")
            e_fut = ex.submit(self._call, e_prompt, "Explorer")
            guardian_raw = g_fut.result()
            explorer_raw = e_fut.result()

        guardian = self._parse_json(guardian_raw) or {}
        explorer = self._parse_json(explorer_raw) or {}
        if not guardian and not explorer:
            return None

        r_prompt = _SALVAGE_REDUCER.format(
            question=question,
            guardian=json.dumps(guardian, ensure_ascii=False)[:1500],
            explorer=json.dumps(explorer, ensure_ascii=False)[:1500],
        )
        reducer_raw = self._call(r_prompt, "Reducer")
        reducer = self._parse_json(reducer_raw) or {}
        if not reducer:
            return None

        decision = str(reducer.get("decision", "")).lower()
        final_answer = str(reducer.get("answer", "")).strip()
        if decision == "commit" and final_answer:
            return SalvageResult(
                committed=True,
                answer=final_answer,
                reason=str(reducer.get("reason", "")),
                confidence=float(reducer.get("confidence", 0.7)),
            )
        # Abstention confirmed — return None so caller keeps the original
        return None

    # --- internals ---

    def _call(self, prompt: str, role: str) -> str:
        try:
            return self._llm(prompt, f"You are the {role}. Output strict JSON only.") or ""
        except Exception:
            return ""

    @staticmethod
    def _format_memories(results: list[SearchResult]) -> str:
        lines = []
        for r in results:
            meta = r.entry.metadata or {}
            tid = meta.get("turn_id") or meta.get("evidence_id") or f"mem{r.entry.id or 0}"
            sdate = meta.get("session_date", "")
            prefix = f"[{tid}]"
            if sdate:
                prefix += f" ({sdate})"
            lines.append(f"{prefix} {r.entry.content}")
        return "\n".join(lines)

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        if not raw:
            return None
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json|JSON)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
