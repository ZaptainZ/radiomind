"""ManagedRetrieval-1b: remote embedding/rerank consent gate.

Remote retrieval (DashScope / OpenAI-compat embedding+rerank) sends memory text,
queries, and candidate snippets to a third-party API. It must be OFF by default
and require explicit consent (env RADIOMIND_REMOTE_RETRIEVAL or
retrieval.remote.consent). These tests cover the consent helper (both paths),
the egress-status projection, the CLI copy, and the live gate in RadioMind.

Deterministic — no network. DashScopeEmbedder/Reranker `.load()` only check that
a key/base is present; they never call out during construction.
"""
from __future__ import annotations

import pytest

from radiomind.core.config import Config
from radiomind.core.mind import RadioMind
from radiomind.core.retrieval_consent import (
    remote_retrieval_consented,
    remote_retrieval_key_present,
    retrieval_egress_status,
)
from radiomind.cli.main import _render_retrieval_consent, _render_retrieval_status


# ---------------- consent helper: env + config, default off ----------------

def _cfg(**remote) -> Config:
    c = Config()
    if remote:
        c.set("retrieval.remote", remote)
    return c


def test_consent_default_false(monkeypatch):
    monkeypatch.delenv("RADIOMIND_REMOTE_RETRIEVAL", raising=False)
    assert remote_retrieval_consented(_cfg()) is False


def test_consent_via_config(monkeypatch):
    monkeypatch.delenv("RADIOMIND_REMOTE_RETRIEVAL", raising=False)
    assert remote_retrieval_consented(_cfg(consent=True)) is True


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE"])
def test_consent_via_env_true(monkeypatch, val):
    monkeypatch.setenv("RADIOMIND_REMOTE_RETRIEVAL", val)
    assert remote_retrieval_consented(_cfg()) is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off"])
def test_env_false_overrides_config_true(monkeypatch, val):
    # explicit env deny wins even if config consents
    monkeypatch.setenv("RADIOMIND_REMOTE_RETRIEVAL", val)
    assert remote_retrieval_consented(_cfg(consent=True)) is False


def test_consent_none_config(monkeypatch):
    monkeypatch.delenv("RADIOMIND_REMOTE_RETRIEVAL", raising=False)
    assert remote_retrieval_consented(None) is False


# ---------------- key-present detection ----------------

def test_key_present_retrieval_provider():
    c = Config()
    c.set("retrieval_provider", {"base_url": "https://x/v1", "api_key": "k"})
    assert remote_retrieval_key_present(c) is True


def test_key_present_llm_openai_dashscope_only():
    c = Config()
    # generic OpenAI endpoint does NOT count (embedder only reuses dashscope)
    c.set("llm.openai", {"base_url": "https://api.openai.com/v1", "api_key": "k"})
    assert remote_retrieval_key_present(c) is False
    c.set("llm.openai", {"base_url": "https://dashscope.x/v1", "api_key": "k"})
    assert remote_retrieval_key_present(c) is True


def test_key_present_false_when_empty():
    assert remote_retrieval_key_present(Config()) is False


# ---------------- egress-status projection ----------------

class _Remote:
    is_remote = True


class _Local:
    is_remote = False


def test_status_local_fts_when_no_embedder(monkeypatch):
    monkeypatch.delenv("RADIOMIND_REMOTE_RETRIEVAL", raising=False)
    st = retrieval_egress_status(Config(), embedder=None, reranker=None)
    assert st["mode"] == "local FTS only (keyword)"
    assert st["remote_active"] is False


def test_status_local_embedding(monkeypatch):
    monkeypatch.delenv("RADIOMIND_REMOTE_RETRIEVAL", raising=False)
    st = retrieval_egress_status(Config(), embedder=_Local(), reranker=None)
    assert st["mode"] == "local embedding (on-device)"
    assert st["remote_active"] is False


def test_status_remote_active():
    st = retrieval_egress_status(Config(), embedder=_Remote(), reranker=None)
    assert st["mode"] == "remote embedding/rerank enabled"
    assert st["remote_active"] is True


def test_status_remote_reranker_counts():
    st = retrieval_egress_status(Config(), embedder=_Local(), reranker=_Remote())
    assert st["remote_active"] is True


# ---------------- CLI copy ----------------

def test_render_status_disabled_until_consent():
    line = _render_retrieval_status({
        "mode": "local FTS only (keyword)", "remote_active": False,
        "remote_key_present": True, "remote_consented": False,
    })
    assert "disabled until consent" in line
    assert "RADIOMIND_REMOTE_RETRIEVAL=1" in line


def test_render_status_remote_active_says_egress():
    line = _render_retrieval_status({
        "mode": "remote embedding/rerank enabled", "remote_active": True,
        "remote_key_present": True, "remote_consented": True,
    })
    assert "sent to a third-party API" in line


def test_render_status_clean_local_no_hint():
    line = _render_retrieval_status({
        "mode": "local embedding (on-device)", "remote_active": False,
        "remote_key_present": False, "remote_consented": False,
    })
    assert "third-party" not in line
    assert "disabled until consent" not in line


def test_render_consent_onboard_three_states():
    assert "CONSENTED" in _render_retrieval_consent(True, True)
    assert "third-party API" in _render_retrieval_consent(True, False)
    off = _render_retrieval_consent(False, True)
    assert "OFF until consent" in off and "local-only" in off
    none = _render_retrieval_consent(False, False)
    assert "no remote retrieval credentials" in none
    # never claims "private"; default posture is local-only
    assert "local-only" in none


# ---------------- live gate in RadioMind ----------------

def _mind(tmp_path, *, consent, with_key, use_reranker=False):
    cfg = Config()
    cfg.set("general.home", str(tmp_path / ".radiomind"))
    if with_key:
        rp = {"base_url": "https://dashscope.example/v1", "api_key": "fake-key",
              "provider": "dashscope"}
        if use_reranker:
            rp["use_reranker"] = True
        cfg.set("retrieval_provider", rp)
    if consent:
        cfg.set("retrieval.remote", {"consent": True})
    m = RadioMind(config=cfg)
    m.initialize()  # embedder/reranker are resolved in initialize(), not __init__
    return m


def test_gate_no_consent_embedder_never_remote(monkeypatch, tmp_path):
    # With a DashScope key but NO consent, the embedder must never be the remote
    # one — it falls through to local (if installed) or None (FTS).
    monkeypatch.delenv("RADIOMIND_REMOTE_RETRIEVAL", raising=False)
    m = _mind(tmp_path, consent=False, with_key=True)
    try:
        emb = m._embedder
        assert emb is None or not getattr(emb, "is_remote", False)
    finally:
        m.shutdown()


def test_gate_consent_enables_remote_embedder(monkeypatch, tmp_path):
    monkeypatch.delenv("RADIOMIND_REMOTE_RETRIEVAL", raising=False)
    m = _mind(tmp_path, consent=True, with_key=True)
    try:
        emb = m._embedder
        assert emb is not None and getattr(emb, "is_remote", False) is True
    finally:
        m.shutdown()


def test_gate_env_consent_enables_remote_embedder(monkeypatch, tmp_path):
    monkeypatch.setenv("RADIOMIND_REMOTE_RETRIEVAL", "1")
    m = _mind(tmp_path, consent=False, with_key=True)
    try:
        emb = m._embedder
        assert emb is not None and getattr(emb, "is_remote", False) is True
    finally:
        m.shutdown()


def test_gate_no_consent_reranker_never_remote(monkeypatch, tmp_path):
    monkeypatch.delenv("RADIOMIND_REMOTE_RETRIEVAL", raising=False)
    m = _mind(tmp_path, consent=False, with_key=True, use_reranker=True)
    try:
        rr = m._reranker
        assert rr is None or not getattr(rr, "is_remote", False)
    finally:
        m.shutdown()


def test_gate_consent_enables_remote_reranker(monkeypatch, tmp_path):
    monkeypatch.delenv("RADIOMIND_REMOTE_RETRIEVAL", raising=False)
    m = _mind(tmp_path, consent=True, with_key=True, use_reranker=True)
    try:
        rr = m._reranker
        # local cross-encoder (torch/sentence-transformers) is usually absent in
        # the sandbox, so the remote fallback should be the one that loads.
        assert rr is not None and getattr(rr, "is_remote", False) is True
    finally:
        m.shutdown()
