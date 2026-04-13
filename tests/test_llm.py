"""Tests for LLM integration layer (no actual Ollama needed)."""

from radiomind.core.config import Config
from radiomind.core.llm import LLMResponse, LLMRouter, LLMUsageTracker, OllamaBackend


def test_usage_tracker():
    tracker = LLMUsageTracker()
    resp = LLMResponse(
        text="hello", model="qwen3:0.6b", tokens_prompt=10, tokens_completion=20
    )
    tracker.record(resp)
    assert tracker.total_calls == 1
    assert tracker.total_prompt_tokens == 10
    assert tracker.total_completion_tokens == 20
    assert tracker.by_model["qwen3:0.6b"] == 1


def test_ollama_backend_init():
    be = OllamaBackend(host="http://localhost:11434", default_model="phi3:3b")
    assert be.host == "http://localhost:11434"
    assert be.default_model == "phi3:3b"


def test_router_no_backends():
    cfg = Config()
    cfg.set("llm.ollama.host", "")
    cfg.set("llm.openai.base_url", "")
    router = LLMRouter(cfg)
    assert not router.is_available()
    assert router.available_backends() == []


def test_router_with_config():
    cfg = Config()
    router = LLMRouter(cfg)
    assert "ollama" in router._backends
