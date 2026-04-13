"""Tests for community sharing mechanism."""

import json
import time
import pytest

from radiomind.community.pool import (
    CommunityPool,
    ContributeResult,
    detect_pii,
    sanitize_for_sharing,
    contributor_hash,
)
from radiomind.community.scoring import EntryScore, ScoringEngine
from radiomind.core.config import Config
from radiomind.core.mind import RadioMind


# --- PII Detection ---

class TestPII:
    def test_detect_phone_cn(self):
        pii = detect_pii("我的手机号是13812345678")
        assert len(pii) == 1
        assert pii[0][1] == "phone_cn"

    def test_detect_email(self):
        pii = detect_pii("联系我 test@example.com")
        assert len(pii) == 1
        assert pii[0][1] == "email"

    def test_detect_api_key(self):
        pii = detect_pii("sk-41556e7f00c04006aa1804e34735b6e1")
        assert len(pii) == 1
        assert pii[0][1] == "api_key"

    def test_detect_file_path(self):
        pii = detect_pii("看看 /Users/john/Documents/secret.txt")
        assert any(p[1] == "file_path" for p in pii)

    def test_clean_text_passes(self):
        pii = detect_pii("运动有助于改善睡眠质量")
        assert len(pii) == 0

    def test_sanitize_source_tags(self):
        text = "[source:MyProject] 这是一条经验"
        clean = sanitize_for_sharing(text)
        assert "[source:" not in clean
        assert "经验" in clean

    def test_sanitize_paths(self):
        text = "路径在 ~/Documents/project/src 下面"
        clean = sanitize_for_sharing(text)
        assert "~/Documents" not in clean

    def test_contributor_hash_deterministic(self):
        h1 = contributor_hash("user1")
        h2 = contributor_hash("user1")
        assert h1 == h2
        assert len(h1) == 16

    def test_contributor_hash_different_users(self):
        h1 = contributor_hash("user1")
        h2 = contributor_hash("user2")
        assert h1 != h2


# --- Scoring Engine ---

class TestScoring:
    @pytest.fixture
    def engine(self, tmp_path):
        e = ScoringEngine(tmp_path / "scores")
        e.open()
        yield e
        e.close()

    def test_vote_positive(self, engine):
        score = engine.vote("entry1", +1)
        assert score.positive == 1
        assert score.negative == 0

    def test_vote_negative(self, engine):
        score = engine.vote("entry1", -1)
        assert score.negative == 1
        assert score.raw_score == -2  # negative × 2

    def test_multiple_votes(self, engine):
        engine.vote("entry1", +1)
        engine.vote("entry1", +1)
        engine.vote("entry1", +1)
        engine.vote("entry1", -1)
        score = engine.get_score("entry1")
        assert score.positive == 3
        assert score.negative == 1
        assert score.raw_score == 1  # 3 - 1*2

    def test_usage_tracking(self, engine):
        engine.record_usage("entry1")
        engine.record_usage("entry1")
        score = engine.get_score("entry1")
        assert score.usage_count == 2

    def test_verification_threshold(self, engine):
        for _ in range(5):
            engine.record_usage("entry1")
        for _ in range(10):
            engine.vote("entry1", +1)
        score = engine.get_score("entry1")
        assert score.should_verify

    def test_not_verified_low_usage(self, engine):
        for _ in range(10):
            engine.vote("entry1", +1)
        score = engine.get_score("entry1")
        assert not score.should_verify  # usage < 5

    def test_persistence(self, tmp_path):
        e1 = ScoringEngine(tmp_path / "scores")
        e1.open()
        e1.vote("entry1", +1)
        e1.close()

        e2 = ScoringEngine(tmp_path / "scores")
        e2.open()
        score = e2.get_score("entry1")
        assert score is not None
        assert score.positive == 1
        e2.close()

    def test_get_top(self, engine):
        for i in range(5):
            for _ in range(i + 1):
                engine.vote(f"entry{i}", +1)

        top = engine.get_top(3)
        assert len(top) == 3
        assert top[0].positive > top[1].positive

    def test_stats(self, engine):
        engine.vote("a", +1)
        engine.vote("b", -1)
        s = engine.stats()
        assert s["total_entries"] == 2
        assert s["total_votes"] == 2

    def test_vote_log_written(self, engine, tmp_path):
        engine.vote("entry1", +1)
        votes_dir = tmp_path / "scores" / "votes"
        log_files = list(votes_dir.glob("*.jsonl"))
        assert len(log_files) == 1


# --- Community Pool ---

class TestCommunityPool:
    @pytest.fixture
    def mind(self, tmp_path):
        cfg = Config()
        cfg.set("general.home", str(tmp_path / ".radiomind"))
        m = RadioMind(config=cfg)
        m.initialize()
        yield m
        m.shutdown()

    @pytest.fixture
    def pool(self, mind, tmp_path):
        p = CommunityPool(mind, community_dir=tmp_path / "community")
        p.open()
        yield p
        p.close()

    def test_sync_no_source(self, pool, tmp_path):
        result = pool.sync_from_radioheader(tmp_path / "nonexistent")
        assert len(result.errors) > 0

    def test_sync_from_mock_pool(self, pool, tmp_path):
        # Create mock community pool
        pool_dir = tmp_path / "rh_community" / "pool"
        pool_dir.mkdir(parents=True)
        (pool_dir / "sw-test-entry.md").write_text(
            "---\nid: sw-test-entry\ndomain: testing\ntags: test\nrefs: \n---\n\n"
            "context: testing context\nsymptom: test fails\nfix: fix the test\n",
            encoding="utf-8",
        )

        result = pool.sync_from_radioheader(tmp_path / "rh_community")
        assert result.imported == 1

    def test_contribute_empty(self, pool):
        result = pool.contribute()
        assert result.contributed == 0  # no habits yet

    def test_vote(self, pool):
        result = pool.vote("test-entry", +1)
        assert result["final_score"] > 0

    def test_stats(self, pool):
        s = pool.stats()
        assert "total_entries" in s
        assert "pool_files" in s
