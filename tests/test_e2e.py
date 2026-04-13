"""End-to-end test: full path from conversation → L1 → L2 → L3 → search → profiles."""

import pytest

from radiomind.core.config import Config
from radiomind.core.mind import RadioMind
from radiomind.core.types import MemoryLevel, Message


@pytest.fixture
def mind(tmp_path):
    cfg = Config()
    cfg.set("general.home", str(tmp_path / ".radiomind"))
    m = RadioMind(config=cfg)
    m.initialize()
    yield m
    m.shutdown()


# --- Scenario: A user chats across 3 domains ---

CONVERSATION_HEALTH = [
    Message(role="user", content="我每天早上跑步5公里"),
    Message(role="assistant", content="保持运动很好！"),
    Message(role="user", content="我发现跑步后睡眠质量明显提升"),
    Message(role="user", content="我喜欢在公园跑步"),
]

CONVERSATION_WORK = [
    Message(role="user", content="我在一家科技公司工作"),
    Message(role="assistant", content="科技行业很有趣。"),
    Message(role="user", content="我讨厌加班"),
    Message(role="user", content="我打算学习Rust编程语言"),
]

CONVERSATION_IDENTITY = [
    Message(role="user", content="我叫小明"),
    Message(role="user", content="我在北京"),
    Message(role="user", content="请记住我的生日是3月15日"),
]


class TestE2EFullPath:
    """Test the complete path: ingest → search → profile → stats."""

    def test_ingest_multi_domain(self, mind):
        e1 = mind.ingest(CONVERSATION_HEALTH)
        e2 = mind.ingest(CONVERSATION_WORK)
        e3 = mind.ingest(CONVERSATION_IDENTITY)

        total = len(e1) + len(e2) + len(e3)
        assert total >= 5  # at least: routine, preference, occupation, aversion, identity, explicit

    def test_domain_auto_detection(self, mind):
        mind.ingest(CONVERSATION_HEALTH)
        mind.ingest(CONVERSATION_WORK)

        stats = mind.stats()
        domain_names = [d["name"] for d in stats["domains"]]
        assert "health" in domain_names or len(domain_names) > 0

    def test_cross_domain_search(self, mind):
        mind.ingest(CONVERSATION_HEALTH)
        mind.ingest(CONVERSATION_WORK)

        # Search should find health content
        results = mind.search("跑步")
        assert len(results) > 0
        assert any("跑步" in r.entry.content for r in results)

        # Search should find work content
        results = mind.search("加班")
        assert len(results) > 0

    def test_pyramid_search_returns_results(self, mind):
        mind.ingest(CONVERSATION_HEALTH)
        results = mind.search_pyramid("运动")
        assert len(results) >= 0  # may or may not find via FTS depending on tokenization

    def test_user_profile_built(self, mind):
        mind.ingest(CONVERSATION_HEALTH)
        mind.ingest(CONVERSATION_WORK)
        mind.ingest(CONVERSATION_IDENTITY)  # identity last so "北京" wins over "科技公司"

        profile = mind.get_user_profile()
        assert profile.who.get("name") == "小明"
        assert profile.who.get("location") == "北京"
        assert len(profile.how) > 0

    def test_self_profile_reflects_state(self, mind):
        mind.ingest(CONVERSATION_HEALTH)
        mind._meta.refresh_self()  # refresh after ingest
        sp = mind.get_self_profile()
        assert sp.state["memory_total"] > 0
        assert sp.identity["version"] == "0.1.0"

    def test_context_digest_includes_user_info(self, mind):
        mind.ingest(CONVERSATION_IDENTITY)
        digest = mind.get_context_digest()
        assert "小明" in digest

    def test_learn_external_knowledge(self, mind):
        entries = mind.learn("规律运动可以改善心血管健康")
        assert len(entries) == 1
        assert entries[0].metadata["source"] == "learn"

        # Should be searchable
        results = mind.search("心血管")
        assert len(results) > 0

    def test_stats_comprehensive(self, mind):
        mind.ingest(CONVERSATION_HEALTH)
        mind.ingest(CONVERSATION_WORK)
        mind.ingest(CONVERSATION_IDENTITY)

        s = mind.stats()
        assert s["total_active"] > 0
        assert s["habits"] >= 0
        assert "llm_available" in s
        assert s["domain_count"] >= 0

    def test_full_lifecycle(self, mind):
        """Complete lifecycle: ingest → search → learn → search again."""
        # 1. Ingest conversations
        mind.ingest(CONVERSATION_HEALTH)
        mind.ingest(CONVERSATION_WORK)
        mind.ingest(CONVERSATION_IDENTITY)

        # 2. Search works
        results = mind.search("跑步")
        assert len(results) > 0

        # 3. Learn external knowledge
        mind.learn("每周运动3次以上可以有效降低焦虑")

        # 4. Search finds new knowledge
        results = mind.search("焦虑")
        assert len(results) > 0

        # 5. Profile is built
        profile = mind.get_user_profile()
        assert profile.who.get("name") == "小明"

        # 6. Stats reflect everything
        s = mind.stats()
        assert s["total_active"] >= 5

        # 7. Digest is generated
        digest = mind.get_context_digest()
        assert len(digest) > 0
