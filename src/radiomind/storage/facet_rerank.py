"""BioLocalRetrieval-1b — typed-facet rerank for the FTS-only (bare-install) path.

When there is NO embedder and NO reranker, retrieval is keyword-only (FTS/BM25)
and the gold evidence turn is often lexically diluted out of the top-k. The
BioLocalRetrieval-1a offline probe showed a deterministic typed-facet rerank
recovers ~half the FTS→semantic gap with no model (recall@30 0.147 → 0.427) on
number/entity-anchored multi-session queries.

Scope discipline (this is ONLY the bare-install floor lift):
  - Activates ONLY when no embedder and no reranker are present. With a local
    ONNX embedder (recall@30 0.698) or any reranker, this does nothing — those
    paths are strictly better.
  - Query-type GATED. 1a found facets HARM temporal-reasoning / ordering / list
    queries (spurious number/date overlap). Those are skipped.
  - Requires a real anchor (named entity / amount / distinctive number); a query
    with no facet anchor is skipped.
  - Bonus is bounded per-facet-type (and overall) so a single spammy facet can't
    run away. No LLM, no network, no HDC (1a: HDC adds noise, dropped).

Mirrors the 1a probe's tier-B scoring so the offline replay validates the exact
runtime logic.
"""
from __future__ import annotations

import re

from radiomind.core.types import SearchResult

# Fixed weights from 1a (not gold-tuned). Each overlap capped at 3 occurrences.
W_NUMBER = 0.40
W_ENTITY = 0.30
W_PHRASE = 0.25
W_ROLE = 0.08
W_TIME = 0.10
WIDE_FETCH = 200  # FTS candidate pool to rerank, then truncate to max_results

_NUM_RE = re.compile(r"\$?\s?(\d[\d,]*(?:\.\d+)?)\s?(%?)")
_CAP_RE = re.compile(r"\b([A-Z][a-zA-Z0-9&'\-]+(?:\s+[A-Z][a-zA-Z0-9&'\-]+)*)\b")
_WORD_RE = re.compile(r"[a-z0-9]+")
_ROLE_RE = re.compile(r"^\s*\[(user|assistant)\]")
_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})")
_STOP_ENT = {"I", "The", "A", "An", "My", "Im", "Id", "Ill", "Ive", "You", "It",
             "We", "They", "He", "She", "This", "That", "But", "And", "So", "If",
             "When", "What", "Great", "Sure", "Yes", "No", "Of", "How", "Which",
             "Where", "Why", "Who", "Do", "Did", "Is", "Are", "Was", "Were"}

# Skip cohorts: temporal-reasoning / ordering / list. 1a showed facets hurt these.
# Match ordering/temporal *intent*, not bare substrings — "first"/"last"/"before"/
# "after" alone are too common ("last Thursday", "first time") and wrongly skip
# strongly-anchored wins (e.g. cashback-at-SaveMart-last-Thursday). Real ordering
# uses "in what order / order of / earliest / latest / chronological"; real
# temporal uses "when / what date / how long / how many days|weeks|months|years".
_SKIP_RE = re.compile(
    r"(\bin (?:what|which) order\b|\border of\b|\bchronolog\w*|\bsequence\b|"
    r"\bearliest\b|\blatest\b|\bmost recent\b|\blist (?:the|all|my)\b|\brank(?:ed)?\b|"
    r"\bwhen \b|\bwhat (?:day|date|year|month)\b|\bwhich (?:day|date|year|month)\b|"
    r"\bhow long\b|\bhow many (?:days|weeks|months|years)\b)",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[一-鿿]")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM_RE.finditer(text):
        val = m.group(1).replace(",", "")
        if m.group(2) == "%":
            val += "%"
        out.add(val)
    return out


def _entities(text: str) -> set[str]:
    text = _ROLE_RE.sub("", text)
    out = set()
    for m in _CAP_RE.finditer(text):
        phrase = m.group(1).strip()
        toks = [w for w in phrase.split() if w not in _STOP_ENT]
        if toks:
            out.add(" ".join(toks).lower())
    return out


def _bigrams(text: str) -> set[str]:
    words = [w for w in _WORD_RE.findall(_ROLE_RE.sub("", text).lower()) if len(w) > 2]
    return {f"{a} {b}" for a, b in zip(words, words[1:])}


def _month(date_str: str) -> str:
    m = _DATE_RE.search(date_str or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else ""


def query_facets(query: str, q_date: str = "") -> dict:
    return {
        "numbers": _numbers(query),
        "entities": _entities(query),
        "bigrams": _bigrams(query),
        "month": _month(q_date),
    }


def should_rerank(query: str, qf: dict | None = None) -> tuple[bool, str]:
    """Gate: enable only on a clear entity/amount anchor AND not a temporal/
    ordering/list query. CJK is skipped (facet extraction is ASCII-oriented;
    CJK uses the LIKE path)."""
    if _CJK_RE.search(query):
        return False, "cjk_query"
    if _SKIP_RE.search(query):
        return False, "temporal_or_ordering"
    qf = qf or query_facets(query)
    if not (qf["numbers"] or qf["entities"]):
        return False, "no_facet_anchor"
    return True, "anchored"


def _facet_bonus(qf: dict, content: str, role: str, month: str) -> tuple[float, list[str]]:
    cf_num = _numbers(content)
    cf_ent = _entities(content)
    cf_big = _bigrams(content)
    num_ov = len(qf["numbers"] & cf_num)
    ent_ov = len(qf["entities"] & cf_ent)
    phr_ov = len(qf["bigrams"] & cf_big)
    hits: list[str] = []
    if num_ov:
        hits.append(f"number×{num_ov}")
    if ent_ov:
        hits.append(f"entity×{ent_ov}")
    if phr_ov:
        hits.append(f"phrase×{phr_ov}")
    bonus = (W_NUMBER * min(num_ov, 3)
             + W_ENTITY * min(ent_ov, 3)
             + W_PHRASE * min(phr_ov, 3))
    if role == "user":
        bonus += W_ROLE
        hits.append("role")
    if qf["month"] and qf["month"] == month:
        bonus += W_TIME
        hits.append("month")
    return bonus, hits


def rerank(query: str, q_date: str, pool: list[SearchResult],
           max_results: int) -> tuple[list[SearchResult], dict]:
    """Rerank a wide FTS candidate `pool` by FTS-norm + bounded facet bonus.

    Returns (reranked_results, debug). debug always carries `used` + `reason`.
    Pure: mutates only the returned SearchResults' transient .score/.method; does
    NOT write to the stored entries. No-op (returns pool unchanged) when gated off.
    """
    qf = query_facets(query, q_date)
    ok, reason = should_rerank(query, qf)
    debug = {"used": False, "reason": reason, "pool_size": len(pool)}
    if not ok or not pool:
        return pool, debug

    fts_max = max((r.score for r in pool), default=0.0) or 1.0
    promoted = 0
    scored = []
    for r in pool:
        meta = r.entry.metadata if isinstance(r.entry.metadata, dict) else {}
        role = meta.get("role", "")
        month = _month(meta.get("session_date", ""))
        bonus, hits = _facet_bonus(qf, r.entry.content or "", role, month)
        new = (r.score / fts_max) + bonus
        if bonus > 0:
            promoted += 1
        scored.append((new, bonus, hits, r))

    scored.sort(key=lambda t: t[0], reverse=True)
    out: list[SearchResult] = []
    for new, bonus, hits, r in scored:
        if bonus > 0:
            r.score = float(new)
            r.method = "fts_facet"
        out.append(r)
    debug.update({"used": True, "candidates_with_bonus": promoted,
                  "anchors": {"numbers": sorted(qf["numbers"]),
                              "entities": sorted(qf["entities"])[:6]}})
    return out, debug
