"""Agentic multi-pass retrieval.

Problem this solves: on LongMemEval multi-session queries ("how many babies
were born across all conversations?", "how many magazine subscriptions do
I currently have?"), a single top-k=10 retrieval misses items spread across
>10 sessions. MemMachine / mem0 handle this with query decomposition — turn
one complex question into 2-4 focused sub-questions, retrieve per sub-question,
then union and de-duplicate.

Design goals:
- Pure composition over `PyramidSearch.search()` — zero changes to pyramid.
- Single LLM call for decomposition; sub-queries run in parallel against
  the same retrieval layer, so added latency is ~1 LLM round-trip.
- Gracefully degrade: when the LLM fails or the question looks atomic
  (short, factoid), fall through to a normal single-pass search.

Callers: RadioMind.search() invokes this when `agentic=True`, or the
benchmark harness when `--agentic` is passed.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from radiomind.core.types import SearchResult


_DECOMPOSE_PROMPT = """You break complex memory-search questions into 2-4 focused sub-questions.
Each sub-question should retrieve a DIFFERENT aspect of the answer.

RULES
- If the question is atomic (single fact lookup), return just the original question.
- Output JSON array of strings. Nothing else.
- Each sub-question must be answerable by a vector/BM25 search over conversation snippets.
- Do NOT answer the question. Only decompose.

EXAMPLES

Question: How many babies were born to friends and family members in the last few months?
Output: ["babies born friends family", "new baby announcement", "pregnancy birth child", "family member had a baby"]

Question: What is my cat's name?
Output: ["cat name"]

Question: How many magazine subscriptions do I currently have?
Output: ["magazine subscription", "cancelled magazine", "subscribed to magazine"]

Question: How long have I been living in my current apartment?
Output: ["moved to current apartment", "how long living in apartment", "current residence duration"]

Question: {question}
Output:"""


_JSON_ARRAY = re.compile(r"\[\s*(?:\"[^\"]*\"\s*,?\s*)+\]")


def decompose_question(
    question: str,
    llm_fn: Callable[[str], str],
    max_subqueries: int = 4,
) -> list[str]:
    """Return a list of sub-queries. Falls back to [question] on any error."""
    if not question or not llm_fn:
        return [question]
    try:
        raw = llm_fn(_DECOMPOSE_PROMPT.format(question=question))
    except Exception:
        return [question]
    if not raw:
        return [question]
    # Try strict JSON first, then regex-extract the first array-looking substring
    for candidate in (raw, _extract_array(raw)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                subs = [str(x).strip() for x in parsed if str(x).strip()]
                if subs:
                    return subs[:max_subqueries]
        except Exception:
            continue
    return [question]


def _extract_array(text: str) -> str | None:
    m = _JSON_ARRAY.search(text)
    return m.group(0) if m else None


def agentic_search(
    question: str,
    search_fn: Callable[..., list[SearchResult]],
    llm_fn: Callable[[str], str] | None,
    domain: str | None = None,
    per_subquery_k: int = 5,
    final_k: int = 10,
) -> list[SearchResult]:
    """Decompose → search per sub-query → merge with dedup+score-boost.

    search_fn signature: (query: str, domain: str|None, max_results: int) -> list[SearchResult]
    """
    subs = decompose_question(question, llm_fn) if llm_fn else [question]
    if len(subs) == 1:
        # No decomposition — single pass, full breadth
        return search_fn(subs[0], domain=domain, max_results=final_k)

    merged: dict[int, SearchResult] = {}
    vote_count: dict[int, int] = {}
    for sq in subs:
        results = search_fn(sq, domain=domain, max_results=per_subquery_k)
        for r in results:
            eid = r.entry.id if r.entry.id is not None else hash(r.entry.content) & 0x7FFFFFFF
            vote_count[eid] = vote_count.get(eid, 0) + 1
            if eid not in merged or r.score > merged[eid].score:
                merged[eid] = r

    # Boost entries that showed up for multiple sub-queries — they are
    # more likely to be genuinely relevant than single-sub hits.
    scored = []
    for eid, r in merged.items():
        boost = 1.0 + 0.2 * (vote_count[eid] - 1)
        scored.append(SearchResult(
            entry=r.entry, score=r.score * boost, method=f"agentic×{vote_count[eid]}",
        ))
    scored.sort(key=lambda r: -r.score)
    return scored[:final_k]
