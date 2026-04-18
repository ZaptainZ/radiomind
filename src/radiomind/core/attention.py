"""Query attention classifier — RadioMind's 4th architecture law.

Every architectural layer should answer explicitly: "what attention pattern
does this serve?" This module implements the **query-time** attention
classification that routes a query to the appropriate downstream pipeline:

  aggregation   — "how many X", list enumeration, counting across sessions
                  → triggers atomic decomposition on retrieved turns
  disambiguation — "previous / former / current / latest" present
                  → triggers meta-calibrated answer + KG bitemporal query
  narrative     — "why / how did / what happened / trajectory"
                  → keeps raw turns, skips decomposition
  comparison    — "which X is more / compare A and B"
                  → retrieves both sides, ranks
  lookup        — default factoid lookup (what/when/where/who)
                  → standard pyramid search

Tags are NOT mutually exclusive; one query can carry multiple signatures
(e.g. "How many doctors did I visit, and which one was the best?" is
aggregation+comparison). Downstream modules can choose to honor one tag,
all, or fuse them.
"""
from __future__ import annotations

import re


AGGREGATION_MARKERS = (
    "how many", "how much", "total", "sum up", "count", "listed all",
    "list all", "list every", "enumerate", "across all", "across sessions",
    "how often", "how frequently", "in all", "altogether",
    "几个", "几条", "几次", "多少", "总共", "一共", "总和", "总数",
    "列出所有", "列举", "全部", "所有",
)

DISAMBIGUATION_MARKERS = (
    "previous", "former", "old", "original", "earlier",
    "current", "latest", "most recent", "now", "nowadays",
    "之前", "原来", "以前", "早先", "现在", "当前", "最近", "目前",
)

NARRATIVE_MARKERS = (
    "why did", "why do", "why was", "why were",
    "how did you feel", "how did it go", "trajectory",
    "thought process", "reasoning", "rationale",
    "what happened after", "what led to",
    "为什么", "怎么想的", "如何决定", "当时怎么", "心路历程",
)

COMPARISON_MARKERS = (
    "which is", "which was", "compare", "more than", "less than",
    "better than", "worse than", "versus", " vs ", "either",
    "比", "更", "相比", "哪个", "谁更", "哪一个",
)

# Strong lookup indicators (no other signal present)
LOOKUP_MARKERS = (
    "what is", "what was", "where is", "where did", "where was",
    "who is", "who was", "when did", "when was",
    "什么", "在哪", "哪儿", "是谁", "什么时候",
)


def classify(query: str) -> list[str]:
    """Return applicable attention types for this query.

    Multi-label: one query can be both aggregation AND comparison. Callers
    decide how to fuse; the common case is "if aggregation is present,
    always run atomic decomposition" — other tags add to but don't
    override that.

    Always returns at least one tag ('lookup' as default).
    """
    ql = query.lower()
    tags: list[str] = []
    if any(m in ql for m in AGGREGATION_MARKERS):
        tags.append("aggregation")
    if any(m in ql for m in DISAMBIGUATION_MARKERS):
        tags.append("disambiguation")
    if any(m in ql for m in NARRATIVE_MARKERS):
        tags.append("narrative")
    if any(m in ql for m in COMPARISON_MARKERS):
        tags.append("comparison")
    if not tags:
        tags.append("lookup")
    return tags


def is_aggregation(query: str) -> bool:
    """Fast path: does this query need atomic decomposition over retrieved turns?"""
    return "aggregation" in classify(query)


def is_disambiguation(query: str) -> bool:
    """Fast path: does this query carry previous/current/original semantics?"""
    return "disambiguation" in classify(query)


# Extract the principal entity from an aggregation query for focused
# decomposition. Falls back to returning the query itself when no
# obvious focus exists. Cheap regex — not a substitute for NER.
_ENTITY_REGEXES = (
    re.compile(r"how many (?:different )?([a-z][a-z\-]+(?:s)?)", re.IGNORECASE),
    re.compile(r"how much ([a-z][a-z\-]+)", re.IGNORECASE),
    re.compile(r"几个不同的?([^\s，。？]+)"),
    re.compile(r"多少([^\s，。？]+)"),
    re.compile(r"list (?:all |every )?([a-z][a-z\-]+(?:s)?)", re.IGNORECASE),
)


def extract_focus_entity(query: str) -> str | None:
    """Best-effort extraction of the noun the aggregation is about.

    Used to narrow decomposition: "How many doctors did I see?" → focus='doctors'
    gives the decomposer a tighter extraction target than re-chewing the full
    question.
    """
    for pattern in _ENTITY_REGEXES:
        m = pattern.search(query)
        if m:
            return m.group(1).strip()
    return None
