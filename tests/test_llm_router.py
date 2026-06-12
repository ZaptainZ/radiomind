"""LLMRouter-1b: generic config profiles, shared ollama probe, loud fallback.

Deterministic — mock the no-proxy opener; no network, no LLM.
1a audit defects locked as regressions:
  A. [llm.dashscope]/[llm.openrouter] sections were never built;
  B. config-path ollama probe ignored the model list (drifted from llm_auto);
  C. generate() silently fell back to the first 'available' backend.
"""
from __future__ import annotations

import io
import json
import logging

import pytest

import radiomind.core.llm as llm_mod
from radiomind.core.config import Config
from radiomind.core.llm import (
    CallableBackend,
    LLMRouter,
    OllamaBackend,
    OpenAICompatBackend,
    ollama_ready,
)


def _config(llm_section: dict) -> Config:
    c = Config()
    c.set("llm", llm_section)
    return c


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeOpener:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def open(self, req, timeout=0):
        if self.error:
            raise self.error
        return _FakeResp(json.dumps(self.payload).encode())


# ---------------- Fix A: 通用 profile 构建 ----------------

def test_dashscope_profile_built_and_routable():
    r = LLMRouter(_config({
        "default_backend": "dashscope",
        "dashscope": {"base_url": "https://ds.example/v1", "api_key": "k",
                      "model": "deepseek-v3.2"},
    }))
    assert "dashscope" in r._backends
    be = r._backends["dashscope"]
    assert isinstance(be, OpenAICompatBackend)
    assert be.base_url == "https://ds.example/v1"
    assert be.default_model == "deepseek-v3.2"


def test_openrouter_profile_built():
    r = LLMRouter(_config({
        "openrouter": {"base_url": "https://or.example/v1", "api_key": "k2"},
    }))
    assert "openrouter" in r._backends


def test_reserved_keys_never_built_as_profiles():
    r = LLMRouter(_config({
        "models": {"economy": "qwen-turbo"},
        "default_backend": "dashscope",
    }))
    assert "models" not in r._backends
    assert "default_backend" not in r._backends


def test_profile_without_key_skipped():
    r = LLMRouter(_config({"half": {"base_url": "https://x"}}))
    assert "half" not in r._backends


# ---------------- 现有 ollama/openai 构建回归锁定 ----------------

def test_legacy_sections_built_unchanged():
    r = LLMRouter(_config({
        "ollama": {"host": "http://localhost:11434", "model": "m1"},
        "openai": {"base_url": "https://oa.example/v1", "api_key": "k",
                   "model": "deepseek-chat"},
    }))
    assert isinstance(r._backends["ollama"], OllamaBackend)
    assert r._backends["ollama"].default_model == "m1"
    assert isinstance(r._backends["openai"], OpenAICompatBackend)
    assert r._backends["openai"].default_model == "deepseek-chat"


def test_legacy_openai_not_overwritten_by_generic_loop():
    r = LLMRouter(_config({
        "openai": {"base_url": "https://oa.example/v1", "api_key": "k",
                   "model": "legacy-model"},
    }))
    assert r._backends["openai"].default_model == "legacy-model"


# ---------------- Fix B: 共享 ollama 探活 ----------------

def test_ollama_ready_false_when_no_models(monkeypatch):
    monkeypatch.setattr(llm_mod, "_NO_PROXY_OPENER", _FakeOpener({"models": []}))
    assert not ollama_ready("http://localhost:11434")


def test_ollama_ready_true_with_model(monkeypatch):
    monkeypatch.setattr(llm_mod, "_NO_PROXY_OPENER",
                        _FakeOpener({"models": [{"name": "qwen"}]}))
    assert ollama_ready("http://localhost:11434")


def test_ollama_ready_false_on_connection_error(monkeypatch):
    monkeypatch.setattr(llm_mod, "_NO_PROXY_OPENER",
                        _FakeOpener(error=OSError("refused")))
    assert not ollama_ready("http://localhost:11434")


def test_backend_is_available_uses_shared_probe(monkeypatch):
    monkeypatch.setattr(llm_mod, "_NO_PROXY_OPENER", _FakeOpener({"models": []}))
    assert not OllamaBackend().is_available()


def test_llm_auto_p3_uses_shared_probe(monkeypatch):
    monkeypatch.setattr(llm_mod, "_NO_PROXY_OPENER", _FakeOpener({"models": []}))
    from radiomind.core.llm_auto import _from_ollama
    assert _from_ollama() is None


# ---------------- Fix C: 兜底必须可观测 ----------------

def _router_with_live_backend(default: str) -> LLMRouter:
    r = LLMRouter(_config({"default_backend": default}))
    r._backends["live"] = CallableBackend(lambda p, s="": "ok", name="live")
    return r


def test_fallback_warns_once(caplog):
    r = _router_with_live_backend("dashscope")  # 不存在的 default
    with caplog.at_level(logging.WARNING, logger="radiomind.core.llm"):
        r.generate("hi")
        r.generate("hi again")
    warns = [rec for rec in caplog.records if "falling back" in rec.message]
    assert len(warns) == 1
    assert "dashscope" in warns[0].message and "live" in warns[0].message


def test_no_warning_when_default_present(caplog):
    r = _router_with_live_backend("live")
    r.config.set("llm.default_backend", "live")
    with caplog.at_level(logging.WARNING, logger="radiomind.core.llm"):
        r.generate("hi")
    assert not [rec for rec in caplog.records if "falling back" in rec.message]


def test_nothing_available_raises(monkeypatch):
    monkeypatch.setattr(llm_mod, "_NO_PROXY_OPENER",
                        _FakeOpener(error=OSError("down")))
    r = LLMRouter(_config({"ollama": {"host": "http://localhost:11434"}}))
    with pytest.raises(RuntimeError, match="No LLM backend available"):
        r.generate("hi")


# ---------------- per-profile timeout（炼化级长输出需要 >45s） ----------------

def test_profile_timeout_passthrough():
    r = LLMRouter(_config({
        "dashscope": {"base_url": "https://ds.example/v1", "api_key": "k",
                      "model": "m", "timeout": 120},
    }))
    assert r._backends["dashscope"].timeout == 120


def test_profile_timeout_default_45():
    r = LLMRouter(_config({
        "dashscope": {"base_url": "https://ds.example/v1", "api_key": "k"},
    }))
    assert r._backends["dashscope"].timeout == 45
