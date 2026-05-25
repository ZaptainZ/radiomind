"""Tests for the RADIOMIND_CQ4_VARIANT env-var diagnostic hook
in mind.run_evidence_candidates.

The hook lets diagnostic audits force three candidate-block
variants without changing production behavior:
  - A (default / unset): full extraction + render, unchanged.
  - B: return "" early — no candidate block injected.
  - C: extract larger top_k first, filter to relation==topic_keyword,
       render the full filtered set (no truncate). Prevents the
       v1 bug where dragon-rank-15 was silently dropped before
       the filter could see it.

Production runner does NOT set the env-var. Default behavior
must be byte-identical to a run with no hook at all.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class _FakeMemoryEntry:
    def __init__(self, content: str, turn_id: str, session_date: str = ""):
        self.id = id(self)
        self.content = content
        self.metadata = {"turn_id": turn_id, "session_date": session_date}


class _FakeResult:
    def __init__(self, entry, score=1.0):
        self.entry = entry
        self.score = score
        self.method = "fake"


def _retrieved_for_nate_like():
    """Memories that mirror Nate's pattern: a dialogue turn whose
    text contains conversational openers + embedded image-query
    metadata with a rare topic word.
    """
    return [
        _FakeResult(_FakeMemoryEntry(
            "[user] I love this series. It has adventures, magic, and "
            "great characters - it's a must-read! [Sharing image — "
            "query: fantasy novels dragon cover series.]",
            "D9:14",
        )),
        _FakeResult(_FakeMemoryEntry(
            "[user] Yeah, the kingdom story arc was epic.",
            "D10:1",
        )),
        _FakeResult(_FakeMemoryEntry(
            "[user] Sharing image — query: eternal kingdom game cover art.",
            "D11:5",
        )),
    ]


def _make_mind_with_search(retrieved):
    """Build a RadioMind instance with initialize already short-
    circuited; we only exercise `run_evidence_candidates`."""
    from radiomind.core.mind import RadioMind
    m = RadioMind(llm=lambda p, s="": "")
    # Avoid touching the real store; mark initialized.
    m._initialized = True
    return m


class TestVariantA_Default:
    def test_no_envvar_yields_nonempty_block(self, monkeypatch):
        monkeypatch.delenv("RADIOMIND_CQ4_VARIANT", raising=False)
        m = _make_mind_with_search([])
        retrieved = _retrieved_for_nate_like()
        block = m.run_evidence_candidates(
            query="What is Nate's favorite book series about?",
            retrieved_memories=retrieved,
        )
        assert block, "default variant should produce a candidate block"
        assert "EVIDENCE CANDIDATES" in block

    def test_explicit_a_matches_unset_default(self, monkeypatch):
        m = _make_mind_with_search([])
        retrieved = _retrieved_for_nate_like()
        monkeypatch.delenv("RADIOMIND_CQ4_VARIANT", raising=False)
        block_default = m.run_evidence_candidates(
            query="What is Nate's favorite book series about?",
            retrieved_memories=retrieved,
        )
        monkeypatch.setenv("RADIOMIND_CQ4_VARIANT", "A")
        block_a = m.run_evidence_candidates(
            query="What is Nate's favorite book series about?",
            retrieved_memories=retrieved,
        )
        assert block_default == block_a, (
            "explicit A must be byte-identical to unset default"
        )


class TestVariantB_Suppress:
    def test_b_returns_empty(self, monkeypatch):
        monkeypatch.setenv("RADIOMIND_CQ4_VARIANT", "B")
        m = _make_mind_with_search([])
        retrieved = _retrieved_for_nate_like()
        block = m.run_evidence_candidates(
            query="What is Nate's favorite book series about?",
            retrieved_memories=retrieved,
        )
        assert block == "", "variant B must return empty string"

    def test_b_returns_empty_even_with_rich_memories(self, monkeypatch):
        monkeypatch.setenv("RADIOMIND_CQ4_VARIANT", "B")
        m = _make_mind_with_search([])
        retrieved = _retrieved_for_nate_like() * 3
        assert m.run_evidence_candidates(
            query="any question", retrieved_memories=retrieved,
        ) == ""


class TestVariantC_TopicKeywordOnly:
    def test_c_filters_topic_keyword_before_truncate(self, monkeypatch):
        """Critical regression for the CQ-4 v1 bug: variant C must
        not silently drop topic candidates that rank below the
        default top_k cap. Run on a Nate-like memory set: the
        rendered block MUST contain 'dragon' (rank 12+ in the
        full topic-keyword list)."""
        monkeypatch.setenv("RADIOMIND_CQ4_VARIANT", "C")
        m = _make_mind_with_search([])
        retrieved = _retrieved_for_nate_like()
        block = m.run_evidence_candidates(
            query="What is Nate's favorite book series about?",
            retrieved_memories=retrieved,
        )
        assert block, "variant C should produce a block"
        assert "dragon" in block.lower(), (
            f"variant C must include the 'dragon' topic keyword in "
            f"the block (CQ-4 v1 regression). Block:\n{block}"
        )
        # Should be EVIDENCE CANDIDATES — verify it's the candidate
        # block format, not some other render path.
        assert "EVIDENCE CANDIDATES" in block

    def test_c_block_contains_only_topic_keyword_entries(self, monkeypatch):
        """Variant C should not surface non-topic_keyword relation
        labels in the rendered text — confirms the filter actually
        ran."""
        monkeypatch.setenv("RADIOMIND_CQ4_VARIANT", "C")
        m = _make_mind_with_search([])
        retrieved = _retrieved_for_nate_like()
        block = m.run_evidence_candidates(
            query="What is Nate's favorite book series about?",
            retrieved_memories=retrieved,
        )
        # All `relation=` entries in the block must read topic_keyword.
        import re
        relations_seen = set(re.findall(
            r"relation=([a-z_]+)", block,
        ))
        assert relations_seen == {"topic_keyword"} or relations_seen <= {"topic_keyword"}, (
            f"variant C should render only topic_keyword relations; "
            f"saw {relations_seen}"
        )


class TestVariantUnknown_FallsBackToA:
    def test_garbage_value_treated_as_a(self, monkeypatch):
        """Unknown values default to A (current behavior). Don't
        crash, don't silently change behavior."""
        monkeypatch.setenv("RADIOMIND_CQ4_VARIANT", "X-NONSENSE")
        m = _make_mind_with_search([])
        retrieved = _retrieved_for_nate_like()
        block = m.run_evidence_candidates(
            query="What is Nate's favorite book series about?",
            retrieved_memories=retrieved,
        )
        # Should produce A-like block (non-empty, has EVIDENCE CANDIDATES)
        assert block
        assert "EVIDENCE CANDIDATES" in block
