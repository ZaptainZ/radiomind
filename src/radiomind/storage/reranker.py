"""Optional cross-encoder reranker for pyramid search.

The retrieval pipeline's last +10-20% R@5 usually comes from a cross-encoder
that re-scores each (query, candidate) pair directly rather than relying on
their separately-embedded vectors. This module wraps sentence-transformers'
CrossEncoder with the same graceful-degradation pattern we use for the
embedder: if not installed or fails to load, search just skips the step.

Default model: BAAI/bge-reranker-v2-m3
  - Multilingual (Chinese + English both strong)
  - ~568M params / 2.3 GB disk / ~20-30ms per 20-pair batch on M-series GPU
  - MIT-compatible license

Alternatives the user can plug in:
  - cross-encoder/ms-marco-MiniLM-L-6-v2  (75 MB, English only, fastest)
  - BAAI/bge-reranker-base                (1.1 GB, English, higher quality)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"


def check_reranker_available() -> tuple[bool, str]:
    try:
        import sentence_transformers  # noqa: F401
        return True, ""
    except ImportError:
        return False, (
            "Reranker not available. Install with:\n"
            "  pip install 'radiomind[rerank]'\n"
            "Or: pip install sentence-transformers"
        )


class CrossEncoderReranker:
    """Thin wrapper over sentence-transformers CrossEncoder.

    Lazily downloads the model on first .load(). Subsequent calls reuse
    it. Predict API returns float scores per (query, doc) pair.
    """

    def __init__(self, model_id: str = DEFAULT_MODEL, cache_dir: Path | None = None):
        self._model_id = model_id
        self._cache_dir = cache_dir
        self._model: Any = None

    def load(self) -> bool:
        available, _ = check_reranker_available()
        if not available:
            return False
        try:
            from sentence_transformers import CrossEncoder
            kwargs = {}
            if self._cache_dir is not None:
                kwargs["cache_folder"] = str(self._cache_dir)
            self._model = CrossEncoder(self._model_id, **kwargs)
            return True
        except Exception:
            self._model = None
            return False

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Score each (query, candidate) pair. Higher = more relevant."""
        if self._model is None:
            return [0.0] * len(pairs)
        return [float(s) for s in self._model.predict(pairs)]

    @property
    def is_available(self) -> bool:
        return self._model is not None
