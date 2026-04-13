"""Tests for Hermes Memory Provider adapter."""

import pytest

from radiomind.adapters.hermes import RadioMindProvider, TOOL_SCHEMAS, CONFIG_SCHEMA
from radiomind.core.config import Config


@pytest.fixture
def provider(tmp_path):
    cfg = Config()
    cfg.set("general.home", str(tmp_path / ".radiomind"))
    cfg.save()

    p = RadioMindProvider()
    p.initialize(session_id="test-session", hermes_home=str(tmp_path))
    # Override with test config
    p._mind.config.set("general.home", str(tmp_path / ".radiomind"))
    yield p
    p.shutdown()


class TestProviderBasics:
    def test_name(self):
        p = RadioMindProvider()
        assert p.name == "radiomind"

    def test_is_available(self):
        p = RadioMindProvider()
        assert p.is_available()

    def test_tool_schemas_valid(self):
        for tool in TOOL_SCHEMAS:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

    def test_config_schema_valid(self):
        for field in CONFIG_SCHEMA:
            assert "key" in field
            assert "description" in field


class TestProviderLifecycle:
    def test_initialize(self, provider):
        assert provider._mind is not None

    def test_system_prompt_block(self, provider):
        block = provider.system_prompt_block()
        assert isinstance(block, str)

    def test_prefetch(self, provider):
        result = provider.prefetch("test query")
        assert isinstance(result, str)

    def test_sync_turn(self, provider):
        # sync_turn is non-blocking (daemon thread)
        provider.sync_turn("hello", "hi there")
        import time
        time.sleep(0.5)  # wait for thread
        assert provider._turn_count == 1

    def test_on_memory_write(self, provider):
        provider.on_memory_write("append", "MEMORY.md", "user prefers dark mode")
        stats = provider._mind.stats()
        assert stats["total_active"] > 0


class TestToolCalls:
    def test_search(self, provider):
        provider._mind.learn("test memory for search")
        result = provider.handle_tool_call("radiomind_search", {"query": "test"})
        assert isinstance(result, list)

    def test_learn(self, provider):
        result = provider.handle_tool_call("radiomind_learn", {"text": "new knowledge"})
        assert result["learned"] == 1

    def test_habits(self, provider):
        result = provider.handle_tool_call("radiomind_habits", {"query": "test"})
        assert isinstance(result, list)

    def test_status(self, provider):
        result = provider.handle_tool_call("radiomind_status", {})
        assert "total_active" in result

    def test_unknown_tool(self, provider):
        result = provider.handle_tool_call("nonexistent", {})
        assert "error" in result
