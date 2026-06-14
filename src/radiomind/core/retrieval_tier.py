"""RetrievalUX-1a — retrieval capability tier detection + reranker env advice.

Pure and testable. NO installs, NO downloads, NO runtime retrieval change — only
classifies what is available and produces onboard/doctor copy positioning the
local retrieval ladder:

  FTS-only (+ typed-facet fallback)  bare install — lightweight, always works
  local embedding                    RECOMMENDED — pip install 'radiomind[embedding]'
                                     (on-device ONNX MiniLM ~86MB; text stays local)
  local embedding + local reranker   ADVANCED — best local quality, conditionally
                                     recommended (heavy ~2.3GB; env-checked)
  remote (consented)                 BYOK, consent-gated — NOT a subscription, not
                                     the recommended default

The reranker is recommended only when the machine is a good fit (Apple Silicon or
ample disk); otherwise it is quietly skipped, never pushed.
"""
from __future__ import annotations

import platform
import shutil
from typing import Any

from radiomind.core.retrieval_consent import remote_retrieval_consented

EMBEDDING_INSTALL = "pip install 'radiomind[embedding]'"
RERANKER_INSTALL = "pip install 'radiomind[rerank]'"
EMBEDDING_NOTE = "on-device ONNX MiniLM (~86MB) — text never leaves your machine"
RERANKER_NOTE = "on-device cross-encoder (~2.3GB) — best local retrieval quality"
RERANKER_DISK_EST = "~2.3GB model + Python deps (torch, sentence-transformers)"

_GB = 1024 ** 3
_RERANK_MIN_FREE = 5 * _GB   # 2.3GB model + deps + headroom
_RERANK_NONARM_FREE = 8 * _GB  # more conservative off Apple Silicon


def embedding_available() -> bool:
    try:
        from radiomind.storage.embedding import check_embedding_available
        return check_embedding_available()[0]
    except Exception:
        return False


def reranker_available() -> bool:
    try:
        from radiomind.storage.reranker import check_reranker_available
        return check_reranker_available()[0]
    except Exception:
        return False


def detect_retrieval_tier(
    config: Any,
    *,
    embedding_installed: bool | None = None,
    reranker_installed: bool | None = None,
    remote_consented: bool | None = None,
) -> dict:
    """Classify the current retrieval tier. Args override detection for tests."""
    emb = embedding_available() if embedding_installed is None else embedding_installed
    rr = reranker_available() if reranker_installed is None else reranker_installed
    consented = (remote_retrieval_consented(config)
                 if remote_consented is None else remote_consented)
    if consented:
        tier = "remote (consented)"
    elif emb and rr:
        tier = "local embedding + local reranker"
    elif emb:
        tier = "local embedding"
    else:
        tier = "FTS-only (+ typed-facet fallback)"
    return {
        "tier": tier,
        "embedding_installed": emb,
        "reranker_installed": rr,
        "remote_consented": consented,
    }


def local_reranker_recommendation(
    home: Any = None,
    *,
    machine: str | None = None,
    system: str | None = None,
    free_bytes: int | None = None,
) -> dict:
    """Whether to recommend installing the local cross-encoder reranker on THIS
    machine. Conditional (heavy ~2.3GB) — recommend on Apple Silicon with enough
    disk, or any platform with generous disk; otherwise quietly skip. Pure: pass
    machine/system/free_bytes to bypass detection in tests."""
    mach = (machine if machine is not None else platform.machine()).lower()
    sys_ = (system if system is not None else platform.system()).lower()
    if free_bytes is None:
        try:
            free_bytes = shutil.disk_usage(str(home) if home else ".").free
        except Exception:
            free_bytes = None

    apple_silicon = sys_ == "darwin" and mach in ("arm64", "aarch64")
    free_gb = (free_bytes // _GB) if free_bytes is not None else None

    if free_bytes is not None and free_bytes < _RERANK_MIN_FREE:
        return {
            "recommended": False,
            "reason": (f"advanced reranker skipped for this machine "
                       f"(only ~{free_gb}GB free, needs ~{_RERANK_MIN_FREE // _GB}GB)"),
            "install_command": None,
            "estimated_disk": RERANKER_DISK_EST,
        }
    if apple_silicon:
        return {
            "recommended": True,
            "reason": ("Apple Silicon with sufficient disk — a local cross-encoder "
                       "reranker is a good fit for best local quality"),
            "install_command": RERANKER_INSTALL,
            "estimated_disk": RERANKER_DISK_EST,
        }
    if free_bytes is not None and free_bytes >= _RERANK_NONARM_FREE:
        return {
            "recommended": True,
            "reason": ("sufficient disk — local reranker available (CPU cross-encoder; "
                       "heavier than embedding)"),
            "install_command": RERANKER_INSTALL,
            "estimated_disk": RERANKER_DISK_EST,
        }
    return {
        "recommended": False,
        "reason": ("advanced reranker skipped for this machine "
                   "(conservative default off Apple Silicon)"),
        "install_command": None,
        "estimated_disk": RERANKER_DISK_EST,
    }
