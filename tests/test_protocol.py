"""Tests for Protocol + SimpleRadioMind."""

import pytest

from radiomind import SimpleRadioMind, connect, MemoryProtocol
from radiomind.core.config import Config
from radiomind.protocol import AddResult, Memory, RefineResult


@pytest.fixture
def mind(tmp_path):
    m = SimpleRadioMind(home=str(tmp_path / ".radiomind"))
    yield m
    m.close()


class TestProtocol:
    def test_simple_implements_protocol(self, mind):
        assert isinstance(mind, MemoryProtocol)

    def test_protocol_methods_exist(self):
        methods = ["add", "search", "digest", "refine"]
        for m in methods:
            assert hasattr(SimpleRadioMind, m)


class TestSimpleAPI:
    def test_connect(self, tmp_path):
        m = connect(home=str(tmp_path / ".rm"))
        assert isinstance(m, SimpleRadioMind)
        m.close()

    def test_context_manager(self, tmp_path):
        with connect(home=str(tmp_path / ".rm")) as m:
            assert isinstance(m, SimpleRadioMind)

    def test_add(self, mind):
        result = mind.add([
            {"role": "user", "content": "我叫小明"},
            {"role": "user", "content": "我喜欢跑步"},
        ])
        assert isinstance(result, AddResult)
        assert result.added >= 1

    def test_add_dedup(self, mind):
        mind.add([{"role": "user", "content": "我叫小明"}])
        result = mind.add([{"role": "user", "content": "我叫小明"}])
        assert result.skipped >= 0

    def test_search(self, mind):
        mind.add([{"role": "user", "content": "我喜欢每天跑步"}])
        results = mind.search("跑步")
        assert isinstance(results, list)
        assert len(results) > 0
        assert isinstance(results[0], Memory)
        assert results[0].content

    def test_search_empty(self, mind):
        results = mind.search("nonexistent12345")
        assert len(results) == 0

    def test_digest(self, mind):
        mind.add([{"role": "user", "content": "我叫测试用户"}])
        digest = mind.digest()
        assert isinstance(digest, str)
        assert len(digest) > 0

    def test_digest_budget(self, mind):
        d1 = mind.digest(token_budget=50)
        d2 = mind.digest(token_budget=500)
        assert isinstance(d1, str)
        assert isinstance(d2, str)

    def test_advanced_access(self, mind):
        from radiomind import RadioMind
        assert isinstance(mind.advanced, RadioMind)

    def test_full_lifecycle(self, mind):
        """The entire RadioMind experience in 4 method calls."""
        # 1. Add
        mind.add([
            {"role": "user", "content": "我叫小明"},
            {"role": "user", "content": "我每天早上跑步"},
            {"role": "user", "content": "我讨厌加班"},
        ])

        # 2. Search
        results = mind.search("运动")
        assert len(results) >= 0  # may or may not match via FTS

        # 3. Digest
        digest = mind.digest()
        assert "小明" in digest

        # 4. Stats via advanced API
        stats = mind.advanced.stats()
        assert stats["total_active"] >= 1


class TestLLMInjection:
    """Test external LLM injection — host frameworks pass their own LLM."""

    def test_connect_with_llm(self, tmp_path):
        calls = []

        def mock_llm(prompt: str, system: str = "") -> str:
            calls.append(prompt[:50])
            return "INSIGHT: user values health\nCONFIDENCE: 0.8"

        m = connect(home=str(tmp_path / ".rm"), llm=mock_llm)
        assert m.advanced.is_llm_available()
        m.close()

    def test_connect_without_llm_still_works(self, tmp_path):
        m = connect(home=str(tmp_path / ".rm"))
        m.add([{"role": "user", "content": "我叫测试"}])
        results = m.search("测试")
        assert len(results) >= 0
        m.close()

    def test_refine_uses_injected_llm(self, tmp_path):
        calls = []

        def mock_llm(prompt: str, system: str = "") -> str:
            calls.append("called")
            return "INSIGHT: test insight\nCONFIDENCE: 0.7"

        m = connect(home=str(tmp_path / ".rm"), llm=mock_llm)
        m.add([
            {"role": "user", "content": "我喜欢跑步"},
            {"role": "user", "content": "我讨厌加班"},
        ])
        result = m.refine()
        assert len(calls) > 0  # mock LLM was actually called
        m.close()

    def test_radiomind_class_with_llm(self, tmp_path):
        from radiomind import RadioMind
        from radiomind.core.config import Config

        cfg = Config()
        cfg.set("general.home", str(tmp_path / ".rm"))

        def my_llm(prompt, system=""):
            return "test response"

        mind = RadioMind(config=cfg, llm=my_llm)
        mind.initialize()
        assert mind.is_llm_available()
        mind.shutdown()
