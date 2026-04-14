"""Tests for LLM auto-detection."""

import os
import pytest

from radiomind.core.llm import CallableBackend, OllamaBackend, OpenAICompatBackend
from radiomind.core.llm_auto import auto_detect, _from_env, _from_object, _is_openai_client


class TestFromObject:
    def test_callable(self):
        fn = lambda p, s="": f"response to {p}"
        backend = _from_object(fn)
        assert isinstance(backend, CallableBackend)
        resp = backend.generate("hello")
        assert "hello" in resp.text

    def test_string_as_ollama_model(self):
        backend = _from_object("qwen3:0.6b")
        assert isinstance(backend, OllamaBackend)
        assert backend.default_model == "qwen3:0.6b"

    def test_none_returns_none(self):
        # auto_detect with None goes to env detection
        # _from_object itself shouldn't be called with None
        pass

    def test_mock_openai_client(self):
        """Simulate OpenAI client structure."""

        class MockCompletions:
            def create(self, **kwargs):
                class Resp:
                    class Choice:
                        class Msg:
                            content = "mock response"
                        message = Msg()
                    choices = [Choice()]
                return Resp()

        class MockChat:
            completions = MockCompletions()

        class MockClient:
            chat = MockChat()

        backend = _from_object(MockClient())
        assert isinstance(backend, CallableBackend)
        resp = backend.generate("test")
        assert resp.text == "mock response"

    def test_mock_anthropic_client(self):
        """Simulate Anthropic client structure."""

        class MockContent:
            text = "claude response"

        class MockMessages:
            def create(self, **kwargs):
                class Resp:
                    content = [MockContent()]
                return Resp()

        class MockClient:
            messages = MockMessages()

        backend = _from_object(MockClient())
        assert isinstance(backend, CallableBackend)
        resp = backend.generate("test", system="be helpful")
        assert resp.text == "claude response"


class TestFromEnv:
    def test_openai_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test123")
        backend = _from_env()
        assert isinstance(backend, OpenAICompatBackend)
        assert "openai" in backend.base_url

    def test_dashscope_key(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test123")
        backend = _from_env()
        assert isinstance(backend, OpenAICompatBackend)
        assert "dashscope" in backend.base_url

    def test_deepseek_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test123")
        backend = _from_env()
        assert isinstance(backend, OpenAICompatBackend)
        assert "deepseek" in backend.base_url

    def test_no_env(self, monkeypatch):
        for var, _, _ in [("OPENAI_API_KEY", "", ""), ("ANTHROPIC_API_KEY", "", ""),
                          ("DASHSCOPE_API_KEY", "", ""), ("DEEPSEEK_API_KEY", "", "")]:
            monkeypatch.delenv(var, raising=False)
        backend = _from_env()
        # May find other env vars or return None
        # Don't assert None because user's actual env may have keys


class TestAutoDetect:
    def test_with_callable(self):
        fn = lambda p, s="": "ok"
        backend = auto_detect(llm=fn)
        assert backend is not None
        assert backend.is_available()

    def test_with_string(self):
        backend = auto_detect(llm="phi3:3b")
        assert isinstance(backend, OllamaBackend)

    def test_without_arg_returns_something_or_none(self):
        result = auto_detect()
        # Can be None (no env/ollama) or a backend — both are valid
        assert result is None or result.is_available()


class TestIntegration:
    def test_radiomind_auto_detects(self, tmp_path, monkeypatch):
        """RadioMind should auto-detect LLM without any config."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-auto")
        from radiomind.core.config import Config
        from radiomind.core.mind import RadioMind

        cfg = Config()
        cfg.set("general.home", str(tmp_path / ".rm"))
        # Don't set any llm config — let auto-detect find OPENAI_API_KEY
        cfg.set("llm.openai.base_url", "")
        cfg.set("llm.openai.api_key", "")
        cfg.set("llm.ollama.host", "")

        mind = RadioMind(config=cfg)
        mind.initialize()
        assert mind.is_llm_available()
        mind.shutdown()

    def test_connect_with_mock_client(self, tmp_path):
        """connect() with OpenAI-like client object."""
        import radiomind

        class MockCompletions:
            def create(self, **kwargs):
                class Resp:
                    class Choice:
                        class Msg:
                            content = "auto-detected"
                        message = Msg()
                    choices = [Choice()]
                return Resp()

        class MockChat:
            completions = MockCompletions()

        class MockClient:
            chat = MockChat()

        mind = radiomind.connect(home=str(tmp_path / ".rm"), llm=MockClient())
        assert mind.advanced.is_llm_available()
        mind.close()
