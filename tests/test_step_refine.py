"""Tests for step-by-step refinement (host AI mode)."""

import pytest

from radiomind.core.config import Config
from radiomind.core.mind import RadioMind
from radiomind.core.types import MemoryEntry, Message


@pytest.fixture
def mind(tmp_path):
    cfg = Config()
    cfg.set("general.home", str(tmp_path / ".radiomind"))
    m = RadioMind(config=cfg)
    m.initialize()

    m.ingest([
        Message(role="user", content="我每天早上跑步"),
        Message(role="user", content="跑步后睡眠质量好"),
        Message(role="user", content="我讨厌加班"),
    ])
    yield m
    m.shutdown()


class TestChatSteps:
    def test_prepare(self, mind):
        result = mind.refine_step("prepare", domain="health")
        assert result["step"] == "prepare"
        assert result["next_step"] == "guardian"
        assert result["prompt"]  # should have a prompt for guardian
        assert "守护者" in result["prompt"] or "Guardian" in result["prompt"]

    def test_full_debate_flow(self, mind):
        # Step 1: prepare
        r1 = mind.refine_step("prepare", domain="health")
        assert r1["next_step"] == "guardian"

        # Step 2: guardian responds
        r2 = mind.refine_step("guardian", response="These memories are consistent with a health-focused lifestyle.")
        assert r2["next_step"] == "explorer"

        # Step 3: explorer responds
        r3 = mind.refine_step("explorer", response="I notice running correlates with sleep quality — this is a pattern worth capturing.")
        assert r3["next_step"] == "reducer"

        # Step 4: reducer responds
        r4 = mind.refine_step("reducer", response="The running-sleep connection can be merged into one habit statement.")
        assert r4["next_step"] == "synthesize"

        # Step 5: synthesize
        r5 = mind.refine_step("synthesize", response="INSIGHT: Regular morning exercise improves sleep quality\nCONFIDENCE: 0.85")
        assert r5["done"]
        assert len(r5["insights"]) == 1
        assert r5["insights"][0]["confidence"] == 0.85

    def test_prepare_empty_domain(self, mind):
        result = mind.refine_step("prepare", domain="nonexistent")
        assert result["done"]  # no memories, should be done

    def test_prepare_auto_domain(self, mind):
        result = mind.refine_step("prepare")
        # Should auto-pick a domain that has memories
        assert result["prompt"] or result["done"]

    def test_synthesis_none(self, mind):
        mind.refine_step("prepare", domain="health")
        mind.refine_step("guardian", response="ok")
        mind.refine_step("explorer", response="ok")
        mind.refine_step("reducer", response="ok")
        r = mind.refine_step("synthesize", response="NONE")
        assert r["done"]
        assert len(r["insights"]) == 0


class TestDreamSteps:
    def test_dream_prune(self, mind):
        result = mind.refine_step("dream_prune", domain="health")
        if not result["done"]:
            assert result["prompt"]
            assert result["next_step"] == "dream_apply"

    def test_dream_wander(self, mind):
        # Add some habits first
        mind._habits.add_habit("values health", [("user", "health")])
        mind._habits.add_habit("dislikes pressure", [("user", "pressure")])
        mind._habits.add_habit("morning person", [("user", "morning")])

        result = mind.refine_step("dream_wander")
        if not result["done"]:
            assert result["prompt"]
            assert result["next_step"] == "dream_apply"

    def test_dream_apply_archive(self, mind):
        # Get a real memory ID
        entries = mind._store.list_by_domain("health", limit=1)
        if entries:
            mid = entries[0].id
            mind.refine_step("dream_prune", domain="health")
            result = mind.refine_step("dream_apply", response=f"ARCHIVE: {mid}")
            assert any(a["type"] == "archive" for a in result["actions"])

    def test_dream_apply_insight(self, mind):
        mind.refine_step("dream_wander")
        result = mind.refine_step("dream_apply", response="INSIGHT: exercise and sleep are deeply connected")
        assert any(a["type"] == "insight" for a in result["actions"])

    def test_dream_apply_none(self, mind):
        mind.refine_step("dream_prune", domain="health")
        result = mind.refine_step("dream_apply", response="NONE")
        assert result["done"]
        assert len(result["actions"]) == 0


class TestUnknownStep:
    def test_unknown(self, mind):
        result = mind.refine_step("nonexistent")
        assert result["done"]
