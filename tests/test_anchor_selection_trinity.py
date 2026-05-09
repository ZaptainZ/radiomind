"""Tests for `_trinity_select_anchor` — GAP-D / V6.1.1.

V6.1.1 adds retry-with-consistency + abstain (-1) over V6.1:
  - 2 trinity calls; trust only when both agree on chosen_index
  - chosen_index = -1 means "none of these is the user's own event"
  - inconsistent / both-parse-failed / invalid-index → TRINITY_ABSTAIN
"""
from __future__ import annotations

import json

from radiomind.skills.age_interval import (
    _trinity_select_anchor,
    TRINITY_ABSTAIN,
)


class _StubLLM:
    """Returns same canned trinity JSON every call. Tracks call count."""

    def __init__(self, canned: dict | str):
        self._text = canned if isinstance(canned, str) else json.dumps(canned)
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, system=""):
        self.calls += 1
        class _R: pass
        r = _R()
        r.text = self._text
        return r


class _SequenceStubLLM:
    """Returns different canned responses across sequential calls.

    Used to test V6.1.1's retry-consistency: when call 1 vs call 2
    disagree, trinity must abstain (not pick).
    """

    def __init__(self, canned_sequence: list):
        self._seq = [json.dumps(c) if isinstance(c, dict) else c for c in canned_sequence]
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, system=""):
        idx = min(self.calls, len(self._seq) - 1)
        self.calls += 1
        class _R: pass
        r = _R()
        r.text = self._seq[idx]
        return r


def _ok_response(idx: int) -> dict:
    return {
        "stances": [
            {"name": "literal-match", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "semantic-paraphrase", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "temporal-context", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
        ],
        "final_answer": f"candidate {idx}",
        "confidence": 0.85,
        "chosen_index": idx,
    }


# === Existing V6.1 tests (semantics preserved or tightened) ===


def test_select_anchor_zero_candidates_returns_none():
    """Empty candidate list → None (skill upstream handles)."""
    llm = _StubLLM(_ok_response(0))
    out = _trinity_select_anchor("graduated college", [], "Q?", llm)
    assert out is None


def test_select_anchor_single_candidate_skips_trinity():
    """Single candidate → return directly without LLM call."""
    llm = _StubLLM(_ok_response(0))
    cands = [("Completed my Bachelor's at age 25", "2018-05-10")]
    out = _trinity_select_anchor("graduated college", cands, "Q?", llm)
    assert out == cands[0]
    assert llm.calls == 0


def test_select_anchor_picks_chosen_index_when_consistent():
    """V6.1.1: trinity needs BOTH calls to agree on idx=1 → candidate[1] wins."""
    llm = _StubLLM(_ok_response(1))
    cands = [
        ("My niece just graduated from high school", "2024-06-15"),
        ("Completed my Bachelor's degree at age 25", "2018-05-10"),
    ]
    out = _trinity_select_anchor(
        "graduated college", cands,
        "How long ago did I graduate from college?", llm,
    )
    assert out == cands[1]
    assert "Bachelor" in out[0]
    assert llm.calls == 2  # V6.1.1 retry-consistency


def test_select_anchor_no_llm_returns_none():
    """No LLM → can't run trinity, return None."""
    cands = [("First", "2020-01-01"), ("Second", "2021-01-01")]
    out = _trinity_select_anchor("event", cands, "Q?", None)
    assert out is None


def test_select_anchor_three_candidates_dimension_pick():
    """3 candidates, trinity picks the temporally-plausible one (consistent)."""
    llm = _StubLLM(_ok_response(2))
    cands = [
        ("I attended a graduation ceremony", "2024-06-01"),
        ("My friend graduated last week", "2024-05-25"),
        ("I completed my Bachelor's at age 25", "2018-05-10"),
    ]
    out = _trinity_select_anchor(
        "graduated college", cands,
        "How many years older am I than when I graduated from college?",
        llm,
    )
    assert out == cands[2]


# === V6.1.1 new tests: retry-consistency + abstain semantics ===


def test_select_anchor_inconsistent_picks_abstain():
    """Call 1 says idx=0, call 2 says idx=1 → ABSTAIN (let semantic search decide)."""
    llm = _SequenceStubLLM([_ok_response(0), _ok_response(1)])
    cands = [
        ("First candidate", "2020-01-01"),
        ("Second candidate", "2021-01-01"),
    ]
    out = _trinity_select_anchor("event", cands, "Q?", llm)
    assert out is TRINITY_ABSTAIN
    assert llm.calls == 2


def test_select_anchor_explicit_abstain_consistent():
    """Both calls return chosen_index=-1 → ABSTAIN (trinity says none right)."""
    llm = _StubLLM(_ok_response(-1))
    cands = [
        ("Third-party event A", "2020-01-01"),
        ("Third-party event B", "2021-01-01"),
    ]
    out = _trinity_select_anchor("event", cands, "Q?", llm)
    assert out is TRINITY_ABSTAIN


def test_select_anchor_explicit_abstain_inconsistent_with_pick():
    """Call 1 abstains (-1), call 2 picks idx=0 → ABSTAIN (conservative)."""
    llm = _SequenceStubLLM([_ok_response(-1), _ok_response(0)])
    cands = [
        ("Candidate A", "2020-01-01"),
        ("Candidate B", "2021-01-01"),
    ]
    out = _trinity_select_anchor("event", cands, "Q?", llm)
    assert out is TRINITY_ABSTAIN


def test_select_anchor_one_parse_failed_one_picked_abstains():
    """Call 1 unparseable JSON, call 2 picks idx=0 → ABSTAIN."""
    llm = _SequenceStubLLM(["not valid json {", _ok_response(0)])
    cands = [
        ("First", "2020-01-01"),
        ("Second", "2021-01-01"),
    ]
    out = _trinity_select_anchor("event", cands, "Q?", llm)
    assert out is TRINITY_ABSTAIN


def test_select_anchor_both_parse_failed_abstains():
    """Both calls unparseable → ABSTAIN (V6.1.1 conservative; V6.1 fell back to candidates[0])."""
    llm = _StubLLM("not valid json {")
    cands = [
        ("First", "2020-01-01"),
        ("Second", "2021-01-01"),
    ]
    out = _trinity_select_anchor("event", cands, "Q?", llm)
    assert out is TRINITY_ABSTAIN


def test_select_anchor_invalid_index_consistent_abstains():
    """Both calls return chosen_index=99 (out of range) → ABSTAIN.

    V6.1 fell back to candidates[0]; V6.1.1 routes to semantic search.
    """
    llm = _StubLLM(_ok_response(99))
    cands = [
        ("First", "2020-01-01"),
        ("Second", "2021-01-01"),
    ]
    out = _trinity_select_anchor("event", cands, "Q?", llm)
    assert out is TRINITY_ABSTAIN
