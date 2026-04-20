"""Query attention signature.

Every layer should answer: what is the attention focus? Rather than N
hardcoded booleans for fixed shapes, we compute one `AttentionSignature`
per query — a dict of hints that downstream modules use to decide
whether to route a query through their path.

The legacy list-of-tags API (`classify(query) -> list[str]`) is kept
for backward compatibility with callers that haven't migrated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# --- Raw marker lists (used by both legacy classify and analyze) ---

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

LOOKUP_MARKERS = (
    "what is", "what was", "where is", "where did", "where was",
    "who is", "who was", "when did", "when was",
    "什么", "在哪", "哪儿", "是谁", "什么时候",
)

# Guard against aggregation false positives on temporal/duration phrasings.
_TEMPORAL_HOW_MANY = re.compile(
    r"how (?:many|much|long)\s+"
    r"(?:days?|weeks?|months?|years?|hours?|minutes?|seconds?|nights?|times?)"
    r"(?:\s+ago)?",
    re.IGNORECASE,
)
_HOW_LONG = re.compile(r"\bhow long\b", re.IGNORECASE)
_HOW_OFTEN = re.compile(r"\bhow often\b|\bhow frequently\b", re.IGNORECASE)

_CARDINAL_COUNT_RE = re.compile(
    r"\b(?:how\s+many|how\s+much|total|sum|count|altogether|in\s+all)\b",
    re.IGNORECASE,
)
_CARDINAL_CN_RE = re.compile(r"几(?:个|条|次|件|种|款|只|台|把|部)?|多少|总共|一共|总和|总数")

_TEMPORAL_RE = re.compile(
    r"\b(when|how\s+long|for\s+how\s+many\s+(?:days|weeks|months|years))\b",
    re.IGNORECASE,
)
_OPEN_DOMAIN_RE = re.compile(
    r"\b(?:what|which|who)\b.*\b"
    r"(?:might|could|would|should|maybe|perhaps|likely|probably|possibly|"
    r"consider|enjoy|prefer|recommend|suggest)\b",
    re.IGNORECASE,
)
_SPECIFIC_DETAIL_RE = re.compile(
    r"\b(what|which|where)\s+(?:is|are|was|were|does|do|did|has|have)\s+"
    r"[a-z][a-z]+'?s?\b",
    re.IGNORECASE,
)


# --- Focus entity extraction (shared) ---

_ENTITY_REGEXES = (
    re.compile(
        r"how much (?:did|do|have)\s+i\s+(?:\w+\s+){0,3}"
        r"(?:to|for|at|toward|towards|into|on)\s+"
        r"([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"how many (?:different |distinct |unique )?"
        r"([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
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
    """Extract the noun phrase the query is asking about."""
    for pattern in _ENTITY_REGEXES:
        m = pattern.search(query)
        if not m:
            continue
        phrase = m.group(1).strip().lower()
        tokens = phrase.split()
        while tokens and tokens[-1] in _FOCUS_TAIL_STOPWORDS:
            tokens.pop()
        if tokens:
            return " ".join(tokens)
    return None


# --- Single analyze() — the primary API ---

@dataclass
class AttentionSignature:
    """One dict of hints per query; downstream routes off this.

    wants tells what SHAPE of answer the query targets:
      "count"     — numeric count/total
      "date"      — specific date or duration
      "detail"    — specific attribute of a named subject
      "inference" — open-domain hypothetical expecting a named entity
      "lookup"    — default factoid
    aux_flags adds orthogonal signals the wants doesn't capture
    (e.g. {"disambiguation": True} when query mentions previous/current).
    """
    focus: str | None
    wants: str
    aux_flags: dict[str, bool]


def analyze(query: str) -> AttentionSignature:
    ql = (query or "").lower()

    # aggregation subset: count/total (must not be duration phrasing)
    is_agg = _is_aggregation(ql)
    wants_count = (
        is_agg and bool(_CARDINAL_COUNT_RE.search(query) or _CARDINAL_CN_RE.search(query))
    )

    # temporal precision
    wants_date = bool(_TEMPORAL_RE.search(query))

    # open-domain inference
    wants_inference = bool(_OPEN_DOMAIN_RE.search(query))

    # specific-detail lookup (only when not aggregation/narrative)
    wants_detail = (
        not is_agg
        and not any(m in ql for m in NARRATIVE_MARKERS)
        and bool(_SPECIFIC_DETAIL_RE.search(query))
    )

    # Pick dominant want. Order matters: count > date > inference > detail > lookup.
    # Multi-want queries pick one and record the others in aux_flags.
    if wants_count:
        wants = "count"
    elif wants_date:
        wants = "date"
    elif wants_inference:
        wants = "inference"
    elif wants_detail:
        wants = "detail"
    else:
        wants = "lookup"

    aux: dict[str, bool] = {}
    if any(m in ql for m in DISAMBIGUATION_MARKERS):
        aux["disambiguation"] = True
    if is_agg and not wants_count:
        aux["enumeration"] = True  # aggregation but not cardinal (list-all)
    if any(m in ql for m in COMPARISON_MARKERS):
        aux["comparison"] = True

    return AttentionSignature(
        focus=extract_focus_entity(query),
        wants=wants,
        aux_flags=aux,
    )


def _is_aggregation(ql: str) -> bool:
    if not any(m in ql for m in AGGREGATION_MARKERS):
        return False
    if _HOW_OFTEN.search(ql):
        return True
    if _TEMPORAL_HOW_MANY.search(ql):
        return False
    if _HOW_LONG.search(ql):
        return False
    return True


# --- Backward-compat thin wrappers (keep old call sites green) ---

def classify(query: str) -> list[str]:
    sig = analyze(query)
    tags: list[str] = []
    if sig.wants == "count" or sig.aux_flags.get("enumeration"):
        tags.append("aggregation")
    if sig.aux_flags.get("disambiguation"):
        tags.append("disambiguation")
    if any(m in (query or "").lower() for m in NARRATIVE_MARKERS):
        tags.append("narrative")
    if sig.aux_flags.get("comparison"):
        tags.append("comparison")
    if not tags:
        tags.append("lookup")
    return tags


def is_aggregation(query: str) -> bool:
    sig = analyze(query)
    return sig.wants == "count" or sig.aux_flags.get("enumeration", False)


def is_disambiguation(query: str) -> bool:
    return analyze(query).aux_flags.get("disambiguation", False)


def is_numeric_cardinal(query: str) -> bool:
    return analyze(query).wants == "count"


def is_specific_detail_lookup(query: str) -> bool:
    return analyze(query).wants == "detail"


def is_temporal_precision(query: str) -> bool:
    return analyze(query).wants == "date"


def is_open_domain_specific(query: str) -> bool:
    return analyze(query).wants == "inference"
