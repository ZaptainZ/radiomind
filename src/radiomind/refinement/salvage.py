"""Answer-side salvage — trinity fallback when the answer model abstains.

When the answer model says "information not enough" but retrieval DID
return plausible evidence, run a trinity debate to decide whether to
commit a best-guess or confirm true abstention. Three opposing stances:
literal-support vs plausible-inference vs strict-abstain — chosen by
the trinity primitive per call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from radiomind.core.types import SearchResult


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


@dataclass
class SalvageResult:
    committed: bool
    answer: str
    reason: str
    confidence: float


class AbstentionSalvager:
    """Query-time trinity fallback for answer-layer abstentions."""

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
        if not looks_abstained(answer):
            return None
        if not retrieved:
            return None

        from radiomind.refinement.trinity import debate

        mem_text = self._format_memories(retrieved[:max_mem_lines])
        result = debate(
            task=(
                f"The answer model abstained on this question with "
                f"'insufficient' language, but evidence is present. Decide "
                f"whether to commit a best-guess or confirm true abstention.\n"
                f"Tensions: literal-support (only what's EXPLICITLY stated) "
                f"vs plausible-inference (pattern + world-knowledge "
                f"inference when not stated verbatim) vs strict-abstain "
                f"(genuine ambiguity).\n"
                f"Commit when Explorer-style inference has confidence ≥ 0.6 "
                f"AND ≥ 2 memory citations; or when Guardian-style explicit "
                f"claims actually answer the question. 'What might / could / "
                f"likely' questions are inference-type — prefer commit on "
                f"strong Explorer candidates.\n"
                f"Question: {question}"
            ),
            evidence=mem_text,
            llm=_CallableBackend(self._llm),
            extra_schema=(
                '  "decision": "commit"|"abstain",\n'
                '  "committed_answer": str (empty if abstain),\n'
                '  "confidence": float'
            ),
        )
        if not result:
            return None
        decision = str(result.get("decision") or "").lower()
        committed_answer = str(result.get("committed_answer") or "").strip()
        if decision != "commit" or not committed_answer:
            return None
        try:
            conf = float(result.get("confidence") or 0.7)
        except (TypeError, ValueError):
            conf = 0.7
        return SalvageResult(
            committed=True,
            answer=committed_answer,
            reason=str(result.get("final_answer") or "")[:200],
            confidence=conf,
        )

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


class _CallableBackend:
    """Adapter: trinity.debate expects `.generate(prompt, system)` OR a
    bare callable. The salvager gets a bare callable, so we wrap it in
    an object with `.generate`."""
    def __init__(self, fn):
        self._fn = fn

    def generate(self, prompt, system=""):
        class _R:
            pass
        r = _R()
        r.text = self._fn(prompt, system) or ""
        return r

    def is_available(self):
        return True
