"""DashScope cross-encoder reranker — API-side alternative to local BGE.

Why this exists: the local `sentence_transformers` path needs torch +
transformers + ~2.3 GB BGE model download. In constrained sandboxes (fresh
venv, broken pip proxy) that path isn't available. When the user already
has DashScope credentials, we can fall through to `gte-rerank-v2` — a top-tier
cross-encoder of comparable quality to bge-reranker-v2-m3.

Contract mirrors CrossEncoderReranker: `.load() -> bool`, `.predict(pairs) -> list[float]`.
Pyramid sees no difference.
"""
from __future__ import annotations

import json
import urllib.request


DASHSCOPE_RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
)

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class DashScopeReranker:
    def __init__(self, api_key: str, model: str = "gte-rerank-v2"):
        self._api_key = api_key
        self._model = model
        self._available = bool(api_key)

    def load(self) -> bool:
        return self._available

    @property
    def is_available(self) -> bool:
        return self._available

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Score query-candidate pairs. Returns float list aligned with input."""
        if not pairs or not self._available:
            return [0.0] * len(pairs)
        # All pairs in a reranker call share the same query by construction
        # (pyramid.py passes [(query, doc) for doc in candidates]). Validate
        # and degrade to sequential if that assumption is violated.
        query = pairs[0][0]
        if any(p[0] != query for p in pairs):
            return [self.predict([p])[0] for p in pairs]
        docs = [p[1][:2048] for p in pairs]  # cap doc length (API limit)
        req = urllib.request.Request(
            DASHSCOPE_RERANK_URL,
            data=json.dumps({
                "model": self._model,
                "input": {"query": query, "documents": docs},
                "parameters": {"top_n": len(docs), "return_documents": False},
            }).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with _NO_PROXY_OPENER.open(req, timeout=30) as r:
                body = json.loads(r.read())
        except Exception:
            return [0.0] * len(pairs)
        scores = [0.0] * len(pairs)
        for item in body.get("output", {}).get("results", []):
            i = int(item.get("index", -1))
            if 0 <= i < len(scores):
                scores[i] = float(item.get("relevance_score", 0.0))
        return scores
