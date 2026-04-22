"""Chain-reasoning skill — nested trinity for multi-anchor problems.

Some questions don't decompose to a single arithmetic shape. Example:
  "How many weeks since I recovered from the flu when I went on my
   10th jog outdoors?"

The answer requires chaining three sub-tasks:
  1. Find date of flu recovery (single event lookup)
  2. Find date of the 10th jog (requires counting all jog events
     chronologically, then picking the 10th)
  3. Compute weeks between the two dates

Single-pass LLMs fail here because they can't reliably count within a
long context while also reasoning about date arithmetic. The trinity
primitive helps ONLY if we let it **spawn sub-trinities** — each
stance can own a sub-problem and run its own trinity.debate() to
solve it, then the parent trinity composes.

This skill implements the pattern:
  - Level-1 trinity: decompose the question into sub-problems
  - Per sub-problem: run Level-2 trinity with narrow task
  - Level-1 trinity: compose sub-answers into final

Cost: up to 1 + N LLM calls per chain question (N = sub-problem count).
Triggered only on complex patterns so the everyday path stays cheap.
"""
from __future__ import annotations

import re
from typing import Any

from radiomind.skills.base import Skill, SkillResult


# Trigger patterns — complex temporal chains
_CHAIN_PATTERNS = [
    # "How many weeks had passed since I X when I did Y"
    re.compile(
        r"how\s+many\s+(days?|weeks?|months?|years?)\s+"
        r"(?:had\s+passed\s+|has\s+passed\s+)?"
        r"since\s+i\s+(.+?)\s+when\s+(?:i|my|the)\s+(.+?)[\?\.$]",
        re.IGNORECASE,
    ),
    # "When I did Y, how many X had I done?"
    re.compile(
        r"when\s+i\s+(.+?),?\s+how\s+many\s+(.+?)\s+had\s+i",
        re.IGNORECASE,
    ),
    # "By my Nth X, how long had I been Ying"
    re.compile(
        r"by\s+my\s+\d+\w+\s+(.+?),?\s+how\s+long",
        re.IGNORECASE,
    ),
]


def _format_memories(memories: list, cap: int = 25) -> str:
    lines = []
    for m in memories[:cap]:
        if hasattr(m, "entry"):
            sdate = (m.entry.metadata or {}).get("session_date", "")
            content = m.entry.content or ""
        elif isinstance(m, dict):
            sdate = m.get("created_at") or m.get("session_date", "")
            content = m.get("memory") or m.get("content") or ""
        else:
            continue
        if not content:
            continue
        lines.append(f"[{sdate}] {content[:300].replace(chr(10), ' ')}")
    return "\n".join(lines)


def _trinity_decompose(query: str, evidence: str, llm: Any) -> list[str]:
    """Level-1 trinity: break a complex question into sub-questions."""
    from radiomind.refinement.trinity import debate

    result = debate(
        task=(
            "Decompose this multi-step question into 2-4 ATOMIC sub-questions "
            "a skill layer can solve. Each sub-question must be self-contained "
            "(no pronoun dependencies on others) and have a shape like "
            "'when did X happen' / 'how many Y are there' / 'what date is "
            "the Nth Z'. Tensions to triangulate: atomic-granularity (too "
            "atomic = overflow of calls) vs compositional (must be "
            "answerable independently) vs dependency-order (some sub-Qs "
            "feed others)."
        ),
        evidence=f"Question: {query}\n\nEvidence:\n{evidence}",
        llm=llm,
        extra_schema='  "sub_questions": [str]',
    )
    if not result:
        return []
    sub = result.get("sub_questions") or []
    return [str(s).strip() for s in sub if str(s).strip()][:4]


def _trinity_answer_sub(sub_q: str, evidence: str, llm: Any) -> str:
    """Level-2 trinity: answer one sub-question, three stances."""
    from radiomind.refinement.trinity import debate

    result = debate(
        task=(
            f"Answer this atomic sub-question from the evidence. "
            f"Tensions: literal-extraction (copy from memories) vs counted "
            f"(count distinct occurrences) vs abstain-if-evidence-thin.\n"
            f"Sub-question: {sub_q}"
        ),
        evidence=evidence,
        llm=llm,
    )
    if not result:
        return ""
    return str(result.get("final_answer") or "").strip()


def _trinity_compose(
    original_query: str,
    sub_qa: list[tuple[str, str]],
    llm: Any,
) -> str:
    """Level-1 trinity again: compose sub-answers into final answer."""
    from radiomind.refinement.trinity import debate

    sub_block = "\n".join(
        f"sub_Q: {q}\nsub_A: {a}" for q, a in sub_qa
    )
    result = debate(
        task=(
            f"Given sub-answers, compose the final answer to the original "
            f"question. Tensions: direct-arithmetic (use the sub-answers "
            f"mechanically in the required arithmetic) vs sanity-check "
            f"(reject when sub-answers contradict) vs fallback-abstain "
            f"(if any sub-answer is 'insufficient', propagate).\n"
            f"Original question: {original_query}"
        ),
        evidence=sub_block,
        llm=llm,
    )
    if not result:
        return ""
    return str(result.get("final_answer") or "").strip()


class ChainReasoningSkill(Skill):
    name = "chain_reasoning"
    # Priority below temporal (10) so chain patterns get first crack.
    # Tight match-gate means this skill no-ops quickly on non-chain
    # questions, so the typical path isn't slowed.
    priority = 5

    def match(self, signature: Any) -> bool:
        return True  # gate by pattern inside resolve

    def resolve(self, query: str, memories: list, context: dict) -> SkillResult | None:
        if not any(p.search(query) for p in _CHAIN_PATTERNS):
            return None
        mind = context.get("mind")
        llm = mind._llm if mind else None
        if llm is None:
            return None

        evidence = _format_memories(memories)
        if not evidence:
            return None

        # Level 1: decompose
        sub_questions = _trinity_decompose(query, evidence, llm)
        if len(sub_questions) < 2:
            return None

        # Level 2: answer each sub-question
        sub_qa: list[tuple[str, str]] = []
        for sq in sub_questions:
            sa = _trinity_answer_sub(sq, evidence, llm)
            if not sa or "insufficient" in sa.lower():
                # Abort chain early — missing sub-answer means we can't compose
                return None
            sub_qa.append((sq, sa))

        # Level 1 again: compose
        final = _trinity_compose(query, sub_qa, llm)
        if not final or "insufficient" in final.lower():
            return None

        anchors = [(f"sub: {q[:60]}", a[:80]) for q, a in sub_qa]
        return SkillResult(
            skill_name=self.name,
            answer=final,
            anchors=anchors,
            confidence=0.85,
        )


from radiomind.skills.registry import register  # noqa: E402

register(ChainReasoningSkill())
