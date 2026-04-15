"""Optional LLM-based query rewriter for pyramid search.

For tough queries (single-session-preference, multi-hop), retrieving with
just the original phrasing often misses. A rewriter produces 2-3 variants
that cover different surface forms ("what do I like" → "user's preferences",
"enjoys", "interests in"), retrieves for each, and unions the results
before RRF.

Adds a per-query LLM call (~200-500ms on Qwen). Off by default —
trade latency for recall on a case-by-case basis.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable


REWRITE_PROMPT = """Rewrite this retrieval query into 3 SHORT search-friendly variants.
Variants should cover different surface forms (synonyms, paraphrases, related terms)
while preserving the original intent. Output EXACTLY three lines, one variant each,
nothing else.

Original: {query}

Three variants:"""


class QueryRewriter:
    """Generates 3 LLM-rewritten variants of a search query.

    Caches rewrites keyed by query hash on disk so a benchmark that hits
    the same query twice doesn't pay twice for the LLM call.
    """

    def __init__(self, llm_fn: Callable[[str], str] | None = None, cache_path: Path | None = None):
        """
        llm_fn: (prompt) -> response. If None, rewriter is a no-op.
        cache_path: persistent JSON cache for rewrites.
        """
        self._llm_fn = llm_fn
        self._cache_path = cache_path
        self._cache: dict[str, list[str]] = {}
        if cache_path and cache_path.exists():
            try:
                self._cache = json.loads(cache_path.read_text())
            except Exception:
                self._cache = {}

    def rewrite(self, query: str) -> list[str]:
        """Return [original, variant1, variant2, variant3] (may be fewer)."""
        if not query or self._llm_fn is None:
            return [query] if query else []

        key = hashlib.sha256(query.encode()).hexdigest()[:16]
        if key in self._cache:
            return [query] + self._cache[key]

        try:
            response = self._llm_fn(REWRITE_PROMPT.format(query=query))
        except Exception:
            return [query]

        variants = [ln.strip() for ln in response.strip().split("\n") if ln.strip()]
        # Trim any leading numbering like "1. " / "- "
        cleaned: list[str] = []
        for v in variants:
            for prefix in ("1.", "2.", "3.", "- ", "* ", "1)", "2)", "3)"):
                if v.startswith(prefix):
                    v = v[len(prefix):].strip()
                    break
            if v and v.lower() != query.lower() and len(v) < 200:
                cleaned.append(v)
        cleaned = cleaned[:3]

        self._cache[key] = cleaned
        if self._cache_path:
            try:
                self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                self._cache_path.write_text(json.dumps(self._cache, ensure_ascii=False))
            except Exception:
                pass

        return [query] + cleaned
