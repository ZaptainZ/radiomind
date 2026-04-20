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


# "how many" phrases that are about TIME/DURATION, not enumeration.
# Guard against decompose misfiring on temporal questions — those need
# date arithmetic, not atomic-fact enumeration.
_TEMPORAL_HOW_MANY = re.compile(
    r"how (?:many|much|long)\s+"
    r"(?:days?|weeks?|months?|years?|hours?|minutes?|seconds?|nights?|times?)"
    r"(?:\s+ago)?",
    re.IGNORECASE,
)
# "how long" is almost always duration, not aggregation
_HOW_LONG = re.compile(r"\bhow long\b", re.IGNORECASE)
# "how often" is frequency — it IS aggregation (count per time window)
_HOW_OFTEN = re.compile(r"\bhow often\b|\bhow frequently\b", re.IGNORECASE)


def classify(query: str) -> list[str]:
    """Return applicable attention types for this query.

    Multi-label: one query can be both aggregation AND comparison. Callers
    decide how to fuse; the common case is "if aggregation is present,
    always run atomic decomposition" — other tags add to but don't
    override that.

    Always returns at least one tag ('lookup' as default).

    Aggregation ≠ any "how many" question. "How many days ago" is
    temporal, "how long have I" is duration — neither benefits from
    atomic-entity enumeration. We filter those out explicitly so
    downstream decomposer doesn't pollute the answer prompt for them.
    """
    ql = query.lower()
    tags: list[str] = []

    # Aggregation only if it's genuinely about enumerating entities,
    # not about computing time/duration. "how often" stays aggregation
    # (counting instances). Temporal-how-many and how-long excluded.
    has_agg_marker = any(m in ql for m in AGGREGATION_MARKERS)
    if has_agg_marker:
        is_temporal_how_many = bool(_TEMPORAL_HOW_MANY.search(ql))
        is_how_long = bool(_HOW_LONG.search(ql))
        is_how_often = bool(_HOW_OFTEN.search(ql))
        if is_how_often or (not is_temporal_how_many and not is_how_long):
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


# Numeric-cardinal queries are a strict subset of aggregation: they ask
# for a *count* or a *total amount* of a specific entity class, not a
# list enumeration or cross-session narrative. When both NumericAggregator
# has a cache hit AND the query matches this shape, we can answer from
# the deterministic ground-truth cache and skip (or complement) the
# LLM-based decomposer.
_CARDINAL_COUNT_RE = re.compile(
    r"\b(?:how\s+many|how\s+much|total|sum|count|altogether|in\s+all)\b",
    re.IGNORECASE,
)
_CARDINAL_CN_RE = re.compile(r"几(?:个|条|次|件|种|款|只|台|把|部)?|多少|总共|一共|总和|总数")


def is_numeric_cardinal(query: str) -> bool:
    """Fast path: is this a count/total query (subset of aggregation)?

    Must also be aggregation (filters out 'how many days ago' etc.)
    and must carry a cardinal quantifier keyword.
    """
    if not is_aggregation(query):
        return False
    return bool(_CARDINAL_COUNT_RE.search(query) or _CARDINAL_CN_RE.search(query))


# --- Specific-detail lookup (4th law, new tag for LoCoMo single-hop errors) ---
# Queries that ask about a specific attribute of a specific named subject.
# Typical pattern: "What is X's Y?" / "What does X do while Z?" /
# "What does X's favorite Y?" — gold answer is a concrete noun the user
# mentioned once in a long haystack; top-k retrieval may miss it because
# the mention is peripheral ("Joanna has Tilly the stuffed dog with her
# while writing"). Routing this tag to a keyword-augmented retrieval
# second pass materially improves recall.
_SPECIFIC_DETAIL_RE = re.compile(
    r"\b(what|which|where)\s+(?:is|are|was|were|does|do|did|has|have)\s+"
    r"[a-z][a-z]+'?s?\b",  # requires a possessive or specific subject noun
    re.IGNORECASE,
)


def is_specific_detail_lookup(query: str) -> bool:
    """Fast path: does this query ask for a specific attribute of a named subject?"""
    tags = classify(query)
    if "aggregation" in tags or "narrative" in tags:
        return False
    return bool(_SPECIFIC_DETAIL_RE.search(query))


# --- Temporal precision (for B-class LoCoMo errors: specific date / duration) ---
_TEMPORAL_PRECISION_RE = re.compile(
    r"\b(when|how\s+long|for\s+how\s+many\s+(?:days|weeks|months|years))\b",
    re.IGNORECASE,
)


def is_temporal_precision(query: str) -> bool:
    """Fast path: query about specific date or duration."""
    return bool(_TEMPORAL_PRECISION_RE.search(query))


# --- Open-domain inference (for C-class LoCoMo errors: "what might X enjoy") ---
# Two shapes:
#   "What might X enjoy?" — modal directly after WH
#   "What is a Y that X might enjoy?" / "Which company likely signed X?" —
#   modal or speculation adverb later in the clause
_OPEN_DOMAIN_RE = re.compile(
    r"\b(?:what|which|who)\b.*\b"
    r"(?:might|could|would|should|maybe|perhaps|likely|probably|possibly|"
    r"consider|enjoy|prefer|recommend|suggest)\b",
    re.IGNORECASE,
)


def is_open_domain_specific(query: str) -> bool:
    """Fast path: hypothetical or inferential query expecting a specific named answer."""
    return bool(_OPEN_DOMAIN_RE.search(query))


# Extract the principal entity from an aggregation query for focused
# decomposition. Cheap regex — not a substitute for NER. Ordered by
# specificity so PP-object queries (e.g. "how much did I donate to
# charity") resolve to the PP object ("charity") rather than the auxiliary
# verb ("did I").
_ENTITY_REGEXES = (
    # "how much did I V (to|for|at|toward) X" → X (PP object is the focus)
    re.compile(
        r"how much (?:did|do|have)\s+i\s+(?:\w+\s+){0,3}"
        r"(?:to|for|at|toward|towards|into|on)\s+"
        r"([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
    # "how many (different) X" → X (typical noun-count)
    re.compile(
        r"how many (?:different |distinct |unique )?"
        r"([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
    # "how much X" → X (money/time quantifier)
    re.compile(
        r"how much ([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"list (?:all |every |my )?"
        r"([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
    re.compile(r"几个不同的?([^\s，。？]+)"),
    re.compile(r"多少([^\s，。？]+)"),
)

# Common stop-word tails that shouldn't be part of the focus phrase.
_FOCUS_TAIL_STOPWORDS = {
    "do", "did", "does", "have", "had", "has",
    "are", "were", "was", "is", "am",
    "i", "you", "we", "they", "he", "she", "it",
    "in", "on", "at", "to", "for", "by", "of", "with",
    "my", "your", "our", "their",
    "currently", "now", "already", "still", "also",
    "total", "all", "ever",
}


def extract_focus_entity(query: str) -> str | None:
    """Best-effort extraction of the noun phrase the aggregation is about.

    "How many doctors did I see?"              → 'doctors'
    "How many musical instruments do I own?"   → 'musical instruments'
    "How much money did I raise for charity?"  → 'money'

    Trims trailing auxiliary verbs / pronouns so the focus is a clean
    noun phrase suitable for class-matching in NumericAggregator.
    """
    for pattern in _ENTITY_REGEXES:
        m = pattern.search(query)
        if m:
            phrase = m.group(1).strip().lower()
            tokens = phrase.split()
            # Trim stop-word tail
            while tokens and tokens[-1] in _FOCUS_TAIL_STOPWORDS:
                tokens.pop()
            if not tokens:
                continue
            return " ".join(tokens)
    return None
