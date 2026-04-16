"""DashScope embedding fallback — used when local ONNX MiniLM is unavailable.

Why this exists: local MiniLM needs `tokenizers` (Rust binding) which sometimes
fails to install behind corporate proxies or on fresh sandboxes. When users
already have DashScope (Qwen) credentials in their config, we can fall through
to text-embedding-v3 instead of going cold (FTS-only). Same 1024/1536-dim
float32 bytes contract as EmbeddingEncoder so pyramid code is oblivious.

Enabled automatically when:
  - local embedder fails to load, AND
  - [llm.openai] base_url contains "dashscope" (DashScope-compatible endpoint)
"""
from __future__ import annotations

import json
import struct
import urllib.request
from pathlib import Path


DEFAULT_MODEL = "text-embedding-v3"
DEFAULT_DIM = 1024

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class DashScopeEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str = DEFAULT_MODEL, dim: int = DEFAULT_DIM):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._available = bool(api_key and base_url)

    def load(self) -> bool:
        return self._available

    @property
    def is_available(self) -> bool:
        return self._available

    def dim(self) -> int:
        return self._dim

    def encode(self, text: str) -> bytes | None:
        if not self._available or not text:
            return None
        try:
            req = urllib.request.Request(
                f"{self._base_url}/embeddings",
                data=json.dumps({"model": self._model, "input": text[:2048]}).encode(),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            with _NO_PROXY_OPENER.open(req, timeout=30) as r:
                body = json.loads(r.read())
            vec = body["data"][0]["embedding"]
            if len(vec) != self._dim:
                self._dim = len(vec)
            return struct.pack(f"{len(vec)}f", *vec)
        except Exception:
            return None

    def encode_batch(self, texts: list[str]) -> list[bytes | None]:
        return [self.encode(t) for t in texts]
