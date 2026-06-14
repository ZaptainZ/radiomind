"""ManagedRetrieval-1b — remote retrieval consent gate.

Remote embedding/rerank send memory text, search queries, and candidate
snippets to a third-party API (DashScope / OpenAI-compatible). That is a
real data-egress event, so it must be **explicitly consented and visible**,
never auto-enabled on the mere presence of an LLM/dashscope API key.

Hosted vector DB / cross-device sync / billing are PARKED (see
projectBasicInfo/logs/2026-06-14-managed-retrieval-1a-cc.md). This module only
governs the egress paths that *already exist* in the codebase.

Default posture: **local-only**. Consent is granted via, in precedence order:
  1. env  RADIOMIND_REMOTE_RETRIEVAL  (1/true/yes/on → grant; 0/false/no/off → deny)
  2. config  retrieval.remote.consent = true
"""
from __future__ import annotations

from typing import Any

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")

# Remote embedder/reranker classes set `is_remote = True`; the on-device
# EmbeddingEncoder / CrossEncoderReranker set `is_remote = False`. The gate and
# the status projection rely on this attribute rather than importing the classes
# (avoids import cost / cycles and survives renames).


def remote_retrieval_consented(config: Any) -> bool:
    """True only when the user has explicitly opted into remote retrieval.

    `config` is anything exposing `.get(dotpath, default)` (radiomind Config) or
    None. Env wins over config so a host/operator can force either way.
    """
    import os

    env = os.environ.get("RADIOMIND_REMOTE_RETRIEVAL", "").strip().lower()
    if env in _TRUE:
        return True
    if env in _FALSE:
        return False
    if config is None:
        return False
    return bool(config.get("retrieval.remote.consent", False))


def remote_retrieval_key_present(config: Any) -> bool:
    """True when some remote retrieval credential is configured — i.e. remote
    retrieval *could* run if consented. Used to surface the actionable
    "available but disabled until consent" hint. No network, no side effects.
    """
    if config is None:
        return False

    def _key(section: str) -> str:
        sec = config.get(section, {}) or {}
        return (sec.get("api_key") or "").strip() if isinstance(sec, dict) else ""

    if _key("retrieval_provider") or _key("embedding") or _key("reranker"):
        return True
    # Legacy [llm.openai] piggyback only counts when pointed at a DashScope-style
    # endpoint, which is the only LLM section the embedder/reranker reuse.
    oc = config.get("llm.openai", {}) or {}
    if isinstance(oc, dict):
        base = (oc.get("base_url") or "").lower()
        key = (oc.get("api_key") or "").strip()
        if key and "dashscope" in base:
            return True
    return False


def retrieval_egress_status(
    config: Any, embedder: Any = None, reranker: Any = None
) -> dict:
    """Pure projection of the current retrieval data-egress posture.

    Pass the live `embedder`/`reranker` (status/doctor) to report the *active*
    mode; pass None (onboard, pre-construction) to report only the consent
    posture. No IO.
    """
    consented = remote_retrieval_consented(config)
    key_present = remote_retrieval_key_present(config)

    emb_remote = embedder is not None and bool(getattr(embedder, "is_remote", False))
    rr_remote = reranker is not None and bool(getattr(reranker, "is_remote", False))
    remote_active = emb_remote or rr_remote

    if remote_active:
        mode = "remote embedding/rerank enabled"
    elif embedder is not None:
        mode = "local embedding (on-device)"
    else:
        mode = "local FTS only (keyword)"

    return {
        "mode": mode,
        "remote_consented": consented,
        "remote_key_present": key_present,
        "remote_active": remote_active,
        "embedder_remote": emb_remote,
        "reranker_remote": rr_remote,
    }
