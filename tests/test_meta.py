"""Tests for Meta layer — dual profiling."""

import pytest

from radiomind.core.config import Config
from radiomind.core.types import MemoryEntry
from radiomind.meta.profiles import ProfileManager
from radiomind.storage.database import MemoryStore


@pytest.fixture
def profile_mgr(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    store.open()
    store.add(MemoryEntry(content="test fact", domain="work"))
    store.add(MemoryEntry(content="another fact", domain="health"))

    cfg = Config()
    mgr = ProfileManager(tmp_path / "meta", cfg, store=store)
    mgr.open()
    yield mgr
    mgr.close()
    store.close()


class TestUserProfile:
    def test_extract_name(self, profile_mgr):
        updated = profile_mgr.update_from_text("我叫小明")
        assert updated
        assert profile_mgr.user.who["name"] == "小明"

    def test_extract_location(self, profile_mgr):
        profile_mgr.update_from_text("我在北京")
        assert profile_mgr.user.who["location"] == "北京"

    def test_extract_occupation_from_location_sentence(self, profile_mgr):
        profile_mgr.update_from_text("我在一家科技公司工作")
        assert "科技公司" in profile_mgr.user.who.get("occupation", "")

    def test_extract_preference(self, profile_mgr):
        profile_mgr.update_from_text("我喜欢跑步")
        assert "跑步" in profile_mgr.user.how["preference"]

    def test_extract_goal(self, profile_mgr):
        profile_mgr.update_from_text("我打算学日语")
        assert "日语" in profile_mgr.user.what["goal"]

    def test_accumulate_preferences(self, profile_mgr):
        profile_mgr.update_from_text("我喜欢跑步")
        profile_mgr.update_from_text("我喜欢读书")
        assert "跑步" in profile_mgr.user.how["preference"]
        assert "读书" in profile_mgr.user.how["preference"]

    def test_no_match_returns_false(self, profile_mgr):
        assert not profile_mgr.update_from_text("今天天气真好")

    def test_persistence(self, tmp_path):
        cfg = Config()
        mgr1 = ProfileManager(tmp_path / "meta2", cfg)
        mgr1.open()
        mgr1.update_from_text("我叫测试用户")
        mgr1.close()

        mgr2 = ProfileManager(tmp_path / "meta2", cfg)
        mgr2.open()
        assert mgr2.user.who["name"] == "测试用户"
        mgr2.close()


class TestSelfProfile:
    def test_identity(self, profile_mgr):
        sp = profile_mgr.self_profile
        assert "model" in sp.identity
        assert "active_model" in sp.identity
        assert sp.identity["version"] == "0.1.0"

    def test_state_with_store(self, profile_mgr):
        sp = profile_mgr.self_profile
        assert sp.state["memory_total"] == 2
        assert sp.state["domain_count"] == 2

    def test_capability(self, profile_mgr):
        sp = profile_mgr.self_profile
        assert "ollama_configured" in sp.capability
        assert "cost_mode" in sp.capability


class TestDigest:
    def test_basic_digest(self, profile_mgr):
        profile_mgr.update_from_text("我叫小明")
        profile_mgr.update_from_text("我喜欢编程")
        digest = profile_mgr.get_digest(token_budget=250)
        assert "小明" in digest
        assert len(digest) > 0

    def test_digest_budget(self, profile_mgr):
        profile_mgr.update_from_text("我叫小明")
        digest = profile_mgr.get_digest(token_budget=10)
        assert len(digest) < 100  # rough budget enforcement

    def test_digest_includes_system(self, profile_mgr):
        digest = profile_mgr.get_digest()
        assert "Model" in digest or "Memory" in digest
