"""Answer-side salvage — trinity-based bidirectional abstain gate.

The answer model can mis-call the abstain decision in two directions:
  (a) abstain when memories DO support an answer (under-confidence)
  (b) commit a confident answer when memories DON'T (over-confidence)

`BidirectionalAbstainGate.review()` runs a single trinity debate that
covers both directions: literal-support vs plausible-inference vs
strict-abstain stances independently judge whether the draft is
adequately supported, then converge on one of three actions:
  keep / abstain / rewrite.

`AbstentionSalvager` is preserved for backward compatibility but the
bench harness now goes through the bidirectional gate.
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


# --- Bidirectional abstain gate ----------------------------------------

@dataclass
class GateResult:
    """One-shot decision from the bidirectional abstain gate."""
    action: str          # "keep" | "abstain" | "rewrite"
    answer: str          # final answer to use
    reason: str          # short trinity rationale (debug)
    confidence: float    # 0..1 from trinity self-report


_ABSTAIN_TEXT = "The information provided is not enough."


class BidirectionalAbstainGate:
    """Trinity-based review that runs on EVERY answer (abstain or not)
    and decides whether to keep, override-to-abstain, or rewrite as
    a partial / hedged answer.

    Symmetric design: covers both error directions (under-abstain and
    over-abstain) in a single trinity call. The gate biases toward
    `keep` — only flips when 2+ stances clearly judge the draft
    inconsistent with memories. This avoids regressing the 86 currently-
    correct answers.

    Multi-round / sub-trinity hooks: when the outer trinity returns
    `decision="rewrite"` with `confidence < 0.6`, the gate can fire a
    sub-trinity to refine the rewrite. Initial implementation is
    single-round; sub-trinity is reserved for cases where data shows
    single-round trinity is insufficient.
    """

    def __init__(self, llm_fn: Callable[[str, str], str]):
        """llm_fn: (prompt, system) → response text."""
        self._llm = llm_fn

    def review(
        self,
        question: str,
        draft_answer: str,
        retrieved: list[SearchResult],
        max_mem_lines: int = 40,
    ) -> GateResult | None:
        """Trinity review of (question, draft_answer, memories).

        Returns None when retrieval gave no memories (gate has nothing
        to compare draft against — keep model's call) or when trinity
        fails to produce a parseable verdict.
        """
        if not retrieved:
            return None
        if not draft_answer or not draft_answer.strip():
            return None

        from radiomind.refinement.trinity import debate

        mem_text = AbstentionSalvager._format_memories(retrieved[:max_mem_lines])
        is_abstained = looks_abstained(draft_answer)
        draft_for_prompt = (draft_answer or "").strip()[:1500]

        task = (
            f"You are checking whether the DRAFT answer below is appropriately "
            f"supported by the memories. Three stances independently judge, "
            f"then reconcile:\n"
            f"  - literal-support: does memory text DIRECTLY answer this?\n"
            f"  - plausible-inference: can the answer be derived from indirect "
            f"evidence (range midpoints, pattern + world-knowledge)?\n"
            f"  - strict-abstain: is the question genuinely unanswerable from "
            f"memories?\n\n"
            f"Final decision:\n"
            f"  keep — draft is supported (literal OR inferred); use draft\n"
            f"  abstain — draft is unsupported; replace with "
            f"\"The information provided is not enough.\"\n"
            f"  rewrite — draft is partially supported; output a hedged "
            f"version (range / 'I know X but not Y')\n\n"
            f"Bias to KEEP. Only flip to abstain or rewrite when ≥2 stances "
            f"clearly oppose the draft.\n"
            f"\n"
            f"Question: {question}\n"
            f"Draft answer (model {'abstained' if is_abstained else 'committed'}): "
            f"{draft_for_prompt}"
        )

        result = debate(
            task=task,
            evidence=mem_text,
            llm=_CallableBackend(self._llm),
            extra_schema=(
                '  "decision": "keep"|"abstain"|"rewrite",\n'
                '  "rewritten_answer": str (empty unless rewrite),\n'
                '  "confidence": float (0..1)'
            ),
        )
        if not result:
            return None

        decision = str(result.get("decision") or "keep").lower().strip()
        try:
            conf = float(result.get("confidence") or 0.6)
        except (TypeError, ValueError):
            conf = 0.6
        reason = str(result.get("final_answer") or "")[:200]

        if decision == "abstain":
            return GateResult(
                action="abstain",
                answer=_ABSTAIN_TEXT,
                reason=reason,
                confidence=conf,
            )
        if decision == "rewrite":
            rewritten = str(result.get("rewritten_answer") or "").strip()
            if rewritten:
                return GateResult(
                    action="rewrite",
                    answer=rewritten,
                    reason=reason,
                    confidence=conf,
                )
            # rewrite called but no new text → fall through to keep
        # default: keep (also covers unknown decision values)
        return GateResult(
            action="keep",
            answer=draft_answer,
            reason=reason,
            confidence=conf,
        )
