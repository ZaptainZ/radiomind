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


DEFAULT_MODEL = "text-embedding-v4"
DEFAULT_DIM = 2048  # v4 supports 512/768/1024/2048 — pick 2048 for max semantic capacity

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class DashScopeEmbedder:
    is_remote = True  # sends memory text to a third-party /embeddings API

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
            payload: dict = {"model": self._model, "input": text[:2048]}
            # Pass dimensions only when the model supports it (v4 and newer).
            # v1-v3 reject the field. Cheap way to tell: model name has "v4".
            if "v4" in self._model.lower():
                payload["dimensions"] = self._dim
            req = urllib.request.Request(
                f"{self._base_url}/embeddings",
                data=json.dumps(payload).encode(),
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

    def encode_batch(self, texts: list[str], max_workers: int = 5) -> list[bytes | None]:
        # Workaround for SSL hang seen on some macOS / Aliyun network paths:
        # set RADIOMIND_EMBED_WORKERS=1 to serialize embeddings (slow but stable).
        import os as _os
        _ew = _os.environ.get("RADIOMIND_EMBED_WORKERS", "").strip()
        if _ew.isdigit():
            max_workers = max(1, int(_ew))
        """Batched + parallel encode — 10-50× faster than per-text loop.

        DashScope API limits batch size to 10 texts per request. We chunk
        into batches of 10 and fire `max_workers` in parallel via
        ThreadPoolExecutor. For a 500-turn ingest this cuts embed wall
        time from ~25 min (serial per-text) to ~30s (batched parallel).

        Returns a list aligned with the input texts. Any item for which
        the API call fails gets None in its slot.
        """
        if not texts or not self._available:
            return [None] * len(texts)

        BATCH = 10  # DashScope hard cap
        out: list[bytes | None] = [None] * len(texts)

        def _run_batch(start: int, chunk: list[str]) -> tuple[int, list[bytes | None]]:
            truncated = [t[:2048] if t else "" for t in chunk]
            payload: dict = {"model": self._model, "input": truncated}
            if "v4" in self._model.lower():
                payload["dimensions"] = self._dim
            req = urllib.request.Request(
                f"{self._base_url}/embeddings",
                data=json.dumps(payload).encode(),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with _NO_PROXY_OPENER.open(req, timeout=60) as r:
                    body = json.loads(r.read())
                results: list[bytes | None] = []
                for item in body.get("data", []):
                    vec = item.get("embedding", [])
                    if vec:
                        results.append(struct.pack(f"{len(vec)}f", *vec))
                    else:
                        results.append(None)
                while len(results) < len(chunk):
                    results.append(None)
                return start, results[: len(chunk)]
            except Exception:
                return start, [None] * len(chunk)

        from concurrent.futures import ThreadPoolExecutor
        tasks = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for i in range(0, len(texts), BATCH):
                chunk = texts[i : i + BATCH]
                tasks.append(ex.submit(_run_batch, i, chunk))
            for fut in tasks:
                start, results = fut.result()
                for j, b in enumerate(results):
                    out[start + j] = b
        return out
