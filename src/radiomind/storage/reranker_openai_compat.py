"""OpenAI-compat reranker — hits `{base_url}/rerank` (Cohere-style response).

OpenRouter, Cohere, Jina all speak this exact shape:
  POST /rerank  {"model": str, "query": str, "documents": [str]}
  → {"results": [{"index": int, "relevance_score": float}, ...]}

Wrap for pyramid: same `.load()` / `.predict(pairs)` contract as the
local CrossEncoderReranker and the DashScope reranker.
"""
from __future__ import annotations

import json
import urllib.request


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OpenAICompatReranker:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "cohere/rerank-v3.5",
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._available = bool(api_key and base_url)

    def load(self) -> bool:
        return self._available

    @property
    def is_available(self) -> bool:
        return self._available

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs or not self._available:
            return [0.0] * len(pairs)
        query = pairs[0][0]
        if any(p[0] != query for p in pairs):
            return [self.predict([p])[0] for p in pairs]
        docs = [p[1][:2048] for p in pairs]
        req = urllib.request.Request(
            f"{self._base_url}/rerank",
            data=json.dumps({
                "model": self._model,
                "query": query,
                "documents": docs,
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
        for item in body.get("results", []):
            i = int(item.get("index", -1))
            if 0 <= i < len(scores):
                scores[i] = float(item.get("relevance_score", 0.0))
        return scores
