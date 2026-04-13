"""Embedding encoder — optional, graceful degradation.

Uses ONNX MiniLM-L6-v2 (384 dim, ~86MB) when available.
Falls back silently when onnxruntime/tokenizers not installed.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

EMBEDDING_DIM = 384


def check_embedding_available() -> tuple[bool, str]:
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
        return True, ""
    except ImportError:
        return False, (
            "Embedding not available. Install:\n"
            "  pip install 'radiomind[embedding]'\n"
            "Or: pip install onnxruntime tokenizers"
        )


class EmbeddingEncoder:
    """Encode text to 384-dim vectors using ONNX MiniLM-L6-v2."""

    def __init__(self, model_dir: Path | None = None):
        self._session = None
        self._tokenizer = None
        self._model_dir = model_dir
        self._available = False

    def load(self) -> bool:
        available, _ = check_embedding_available()
        if not available:
            return False

        try:
            from huggingface_hub import snapshot_download
            import onnxruntime as ort
            from tokenizers import Tokenizer

            if self._model_dir and (self._model_dir / "model.onnx").exists():
                model_path = self._model_dir
            else:
                model_path = Path(snapshot_download(
                    "sentence-transformers/all-MiniLM-L6-v2",
                    allow_patterns=["*.onnx", "tokenizer.json"],
                ))

            onnx_path = model_path / "model.onnx"
            if not onnx_path.exists():
                onnx_path = model_path / "onnx" / "model.onnx"

            if not onnx_path.exists():
                return False

            self._session = ort.InferenceSession(str(onnx_path))
            self._tokenizer = Tokenizer.from_file(str(model_path / "tokenizer.json"))
            self._tokenizer.enable_truncation(max_length=512)
            self._tokenizer.enable_padding(length=512)
            self._available = True
            return True
        except Exception:
            self._available = False
            return False

    @property
    def is_available(self) -> bool:
        return self._available

    def encode(self, text: str) -> bytes | None:
        """Encode text to embedding bytes. Returns None if unavailable."""
        if not self._available or self._session is None or self._tokenizer is None:
            return None

        try:
            import numpy as np

            encoded = self._tokenizer.encode(text)
            input_ids = np.array([encoded.ids], dtype=np.int64)
            attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids)

            outputs = self._session.run(
                None,
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "token_type_ids": token_type_ids,
                },
            )

            # Mean pooling over token embeddings
            embeddings = outputs[0][0]  # (seq_len, 384)
            mask = attention_mask[0].astype(np.float32)
            pooled = (embeddings * mask[:, None]).sum(axis=0) / mask.sum()

            # Normalize
            norm = np.linalg.norm(pooled)
            if norm > 0:
                pooled = pooled / norm

            return pooled.astype(np.float32).tobytes()
        except Exception:
            return None

    def encode_batch(self, texts: list[str]) -> list[bytes | None]:
        return [self.encode(t) for t in texts]


def embedding_to_floats(data: bytes) -> list[float]:
    """Convert embedding bytes back to float list."""
    return list(struct.unpack(f"{EMBEDDING_DIM}f", data))


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two embedding byte arrays."""
    import numpy as np
    va = np.frombuffer(a, dtype=np.float32)
    vb = np.frombuffer(b, dtype=np.float32)
    dot = np.dot(va, vb)
    return float(dot)  # already normalized
