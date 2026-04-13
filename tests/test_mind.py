"""Tests for RadioMind main class — full integration (no Ollama needed)."""

import pytest

from radiomind.core.config import Config
from radiomind.core.mind import RadioMind
from radiomind.core.types import Message


@pytest.fixture
def mind(tmp_path):
    cfg = Config()
    cfg.set("general.home", str(tmp_path / ".radiomind"))
    m = RadioMind(config=cfg)
    m.initialize()
    yield m
    m.shutdown()


def test_init_creates_dirs(tmp_path):
    cfg = Config()
    cfg.set("general.home", str(tmp_path / ".radiomind"))
    m = RadioMind(config=cfg)
    m.initialize()
    assert (tmp_path / ".radiomind" / "data").is_dir()
    m.shutdown()


def test_not_initialized_raises():
    m = RadioMind()
    with pytest.raises(RuntimeError, match="not initialized"):
        m.search("test")


def test_ingest_extracts_memories(mind):
    messages = [
        Message(role="user", content="我叫小明"),
        Message(role="user", content="我喜欢跑步"),
        Message(role="assistant", content="好的，小明！"),
        Message(role="user", content="今天天气不错"),
    ]
    entries = mind.ingest(messages)
    assert len(entries) >= 2  # at least identity + preference


def test_ingest_updates_user_profile(mind):
    mind.ingest([Message(role="user", content="我叫测试用户")])
    profile = mind.get_user_profile()
    assert profile.who.get("name") == "测试用户"


def test_search_after_ingest(mind):
    mind.ingest([Message(role="user", content="我喜欢每天跑步锻炼身体")])
    results = mind.search("跑步")
    assert len(results) > 0
    assert any("跑步" in r.entry.content for r in results)


def test_pyramid_search(mind):
    mind.ingest([Message(role="user", content="我每天早上跑步5公里")])
    results = mind.search_pyramid("跑步")
    assert len(results) > 0


def test_learn_adds_fact(mind):
    entries = mind.learn("运动有助于改善睡眠质量")
    assert len(entries) == 1
    assert entries[0].metadata.get("source") == "learn"


def test_stats(mind):
    mind.ingest([Message(role="user", content="我叫小明")])
    s = mind.stats()
    assert s["total_active"] >= 1
    assert "habits" in s
    assert "llm_available" in s


def test_context_digest(mind):
    mind.ingest([Message(role="user", content="我叫小明")])
    digest = mind.get_context_digest()
    assert isinstance(digest, str)
    assert "小明" in digest


def test_self_profile(mind):
    sp = mind.get_self_profile()
    assert sp.identity["version"] == "0.1.0"
    assert "model" in sp.identity
    assert "active_model" in sp.identity
    assert "cost_mode" in sp.identity


def test_update_config(mind):
    mind.update_config("llm.ollama.model", "test-model")
    assert mind.config.get("llm.ollama.model") == "test-model"
