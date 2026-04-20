"""Query-time attention × trinity pipelines for LoCoMo A/B/C error types.

The 4th law says every layer must declare what attention pattern it
serves. The FINAL n=100 LoCoMo error analysis identified three error
shapes that retrieval + plain decomposer can't handle:

  A. Specific-detail lookup  — "What does X do while Y?" gold answer
     lives in one peripheral turn. Handled in `core/attention.py` +
     harness-level keyword augmentation (S3 first pass).

  B. Temporal precision      — "When did X happen?" / "For how long..."
     Needs anchor-event extraction from session_date metadata and
     duration arithmetic. Implemented here as `TemporalPrecisionPipeline`.

  C. Open-domain specific    — "What might X enjoy?" gold is a concrete
     named entity the user referenced once. Retrieval is too wide;
     the answer model gives generic suggestions when a specific one
     lived in memory. Implemented here as `OpenDomainSpecificPipeline`.

Each pipeline is trinity-shaped:
  - Guardian  — verify what's already retrieved / claimed
  - Explorer  — probe adjacent evidence the first pass missed
  - Reducer   — produce a strict answer shape the model can trust

Pipelines are single-LLM-call-each (cheap) and no-op when the attention
classifier doesn't tag the query as their type.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


# --- Temporal precision -------------------------------------------------

TEMPORAL_PRECISION_PROMPT = """You help answer a TEMPORAL precision question.

Question: {question}
Reference date (today): {ref_date}

Retrieved memories (most relevant first; each prefixed with session_date):
{memories}

Trinity sub-tasks:
  Guardian:  identify the anchor event(s) from the memories. Extract
             (subject, action, date) tuples where date comes from the
             prefix [YYYY-MM-DD] or explicit date text in the turn.
  Explorer:  if the answer requires comparing two events' dates or
             computing a duration, chain the supporting evidence.
  Reducer:   produce a STRICT final answer sentence that names the
             date(s) exactly. NO hedging, NO paraphrase.

Output STRICT JSON only:
{{
  "anchor_events": [
    {{"description": "...", "date": "YYYY-MM-DD"}},
    ...
  ],
  "final_answer": "concise sentence with the exact date(s) / duration"
}}
If the evidence is insufficient, output {{"anchor_events": [], "final_answer": "The information provided is not enough."}}."""


@dataclass
class TemporalResult:
    anchor_events: list[dict[str, str]]
    final_answer: str


class TemporalPrecisionPipeline:
    """Run when query is temporal_precision.

    The output `final_answer` is a strict concise sentence that the
    benchmark answer prompt can trust. It's injected ahead of the
    memory block labeled "TEMPORAL GUARDIAN VIEW" so the answer model
    treats it as anchor.
    """

    def __init__(self, llm: Any):
        self._llm = llm

    def run(
        self,
        question: str,
        retrieved_memories: list[dict[str, Any]],
        reference_date: str = "",
        max_memories: int = 20,
    ) -> TemporalResult | None:
        if not self._llm or not retrieved_memories:
            return None

        def _fmt_mem(m: dict[str, Any]) -> str:
            sdate = m.get("created_at") or m.get("session_date") or ""
            txt = (m.get("memory") or m.get("content") or "")[:500].replace("\n", " ")
            if sdate:
                return f"[{sdate}] {txt}"
            return txt

        mem_block = "\n".join(_fmt_mem(m) for m in retrieved_memories[:max_memories])
        prompt = TEMPORAL_PRECISION_PROMPT.format(
            question=question, ref_date=(reference_date or "unknown"),
            memories=mem_block,
        )

        raw = ""
        try:
            if hasattr(self._llm, "generate"):
                resp = self._llm.generate(
                    prompt, system="Output only strict JSON.",
                )
                raw = getattr(resp, "text", "") or ""
            else:
                raw = self._llm(prompt, "Output only strict JSON.")
        except Exception:
            return None

        cleaned = re.sub(r"^```(?:json|JSON)?\s*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
        try:
            obj = json.loads(cleaned)
        except Exception:
            return None

        anchors = obj.get("anchor_events") or []
        answer = str(obj.get("final_answer") or "").strip()
        if not answer:
            return None
        return TemporalResult(
            anchor_events=anchors if isinstance(anchors, list) else [],
            final_answer=answer,
        )

    @staticmethod
    def format_prefix(result: TemporalResult) -> str:
        """Render pipeline result as an answer-prompt prefix."""
        lines = [
            "TEMPORAL PRECISION VIEW "
            "(Guardian-verified date extraction; trust this over retrieval "
            "hedging unless memories contradict the anchor):"
        ]
        for a in result.anchor_events[:5]:
            desc = a.get("description", "")
            date = a.get("date", "")
            if desc and date:
                lines.append(f"- {desc} ({date})")
        lines.append(f"Computed answer: {result.final_answer}")
        return "\n".join(lines) + "\n\n"


# --- Open-domain specific -----------------------------------------------

OPEN_DOMAIN_PROMPT = """You help answer an open-domain specific question.

Question: {question}

Retrieved memories (most relevant first; extract any specific named
entities the user referenced — books, companies, places, songs, etc.):
{memories}

Trinity sub-tasks:
  Guardian:  list every specific named entity the memories mention that
             could plausibly answer the question. Dates, titles, proper
             nouns. Do NOT invent entities not in the memories.
  Explorer:  consider 2-hop: if the user likes A and A is similar to B,
             does a memory explicitly mention B? List only those.
  Reducer:   pick the single MOST SPECIFIC named entity the memories
             support. If no specific entity found, say "insufficient".

Output STRICT JSON only:
{{
  "specific_candidates": ["Candidate A (evidence: turn X)", "Candidate B (evidence: turn Y)"],
  "chosen": "Candidate A",
  "reason": "one-line reason"
}}

If memories contain NO specific named entity for this question, output:
{{"specific_candidates": [], "chosen": "insufficient", "reason": "no named candidate in memories"}}."""


@dataclass
class OpenDomainResult:
    candidates: list[str]
    chosen: str
    reason: str


class OpenDomainSpecificPipeline:
    """Run when query is open_domain_specific.

    Forces the answer to a specific named entity found in memories
    (no abstract hedging). Injects output as "OPEN-DOMAIN PICK" ahead
    of the memory block.
    """

    def __init__(self, llm: Any):
        self._llm = llm

    def run(
        self,
        question: str,
        retrieved_memories: list[dict[str, Any]],
        max_memories: int = 30,
    ) -> OpenDomainResult | None:
        if not self._llm or not retrieved_memories:
            return None

        def _fmt_mem(m: dict[str, Any]) -> str:
            sdate = m.get("created_at") or m.get("session_date") or ""
            txt = (m.get("memory") or m.get("content") or "")[:400].replace("\n", " ")
            if sdate:
                return f"[{sdate}] {txt}"
            return txt

        mem_block = "\n".join(_fmt_mem(m) for m in retrieved_memories[:max_memories])
        prompt = OPEN_DOMAIN_PROMPT.format(question=question, memories=mem_block)

        raw = ""
        try:
            if hasattr(self._llm, "generate"):
                resp = self._llm.generate(
                    prompt, system="Output only strict JSON.",
                )
                raw = getattr(resp, "text", "") or ""
            else:
                raw = self._llm(prompt, "Output only strict JSON.")
        except Exception:
            return None

        cleaned = re.sub(r"^```(?:json|JSON)?\s*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
        try:
            obj = json.loads(cleaned)
        except Exception:
            return None

        chosen = str(obj.get("chosen") or "").strip()
        if not chosen or chosen.lower() == "insufficient":
            return None
        cands = obj.get("specific_candidates") or []
        return OpenDomainResult(
            candidates=[str(c) for c in cands if c][:10],
            chosen=chosen,
            reason=str(obj.get("reason") or "").strip(),
        )

    @staticmethod
    def format_prefix(result: OpenDomainResult) -> str:
        lines = [
            "OPEN-DOMAIN SPECIFIC PICK "
            "(forced-specific: the retrieved memories mention this concrete "
            "entity; do NOT hedge with abstract generic suggestions):"
        ]
        lines.append(f"- chosen: {result.chosen}")
        if result.reason:
            lines.append(f"- reason: {result.reason}")
        if result.candidates:
            lines.append("- other specific candidates found:")
            for c in result.candidates[:3]:
                lines.append(f"  - {c}")
        return "\n".join(lines) + "\n\n"
