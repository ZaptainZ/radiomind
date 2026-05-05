"""Tests for `_trinity_select_anchor` — GAP-D.

When token-match returns multiple plausible anchor candidates, trinity
picks the right one based on three dimensions (literal-match /
semantic-paraphrase / temporal-context). Replaces the earlier
"first token-match wins" heuristic.
"""
from __future__ import annotations

import json

from radiomind.skills.age_interval import _trinity_select_anchor


class _StubLLM:
    """Returns canned trinity JSON; tracks call count."""

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


def test_select_anchor_zero_candidates_returns_none():
    """Empty candidate list → None (skill upstream handles)."""
    llm = _StubLLM({"final_answer": "x", "chosen_index": 0,
                    "stances": [], "confidence": 0.5})
    out = _trinity_select_anchor("graduated college", [], "Q?", llm)
    assert out is None


def test_select_anchor_single_candidate_skips_trinity():
    """Single candidate → return directly without LLM call."""
    llm = _StubLLM({"chosen_index": 0, "final_answer": "x",
                    "stances": [], "confidence": 0.5})
    cands = [("Completed my Bachelor's at age 25", "2018-05-10")]
    out = _trinity_select_anchor("graduated college", cands, "Q?", llm)
    assert out == cands[0]
    assert llm.calls == 0


def test_select_anchor_picks_chosen_index():
    """Trinity returns chosen_index=1 → candidate[1] wins, even if [0] had higher token score."""
    llm = _StubLLM({
        "stances": [
            {"name": "literal-match", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "semantic-paraphrase", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "temporal-context", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
        ],
        "final_answer": "candidate 1 (Bachelor's) is the user's own event",
        "confidence": 0.85,
        "chosen_index": 1,
    })
    cands = [
        # Top-score by token overlap but third-party event
        ("My niece just graduated from high school", "2024-06-15"),
        # The actual user's event (semantic match)
        ("Completed my Bachelor's degree at age 25", "2018-05-10"),
    ]
    out = _trinity_select_anchor("graduated college", cands, "How long ago did I graduate from college?", llm)
    assert out == cands[1]
    assert "Bachelor" in out[0]


def test_select_anchor_invalid_index_falls_back_to_first():
    """Trinity returns out-of-range index → fall back to top-score candidate."""
    llm = _StubLLM({
        "stances": [],
        "final_answer": "x",
        "confidence": 0.4,
        "chosen_index": 99,
    })
    cands = [
        ("First candidate", "2020-01-01"),
        ("Second candidate", "2021-01-01"),
    ]
    out = _trinity_select_anchor("event", cands, "Q?", llm)
    assert out == cands[0]


def test_select_anchor_unparseable_trinity_falls_back():
    """Garbage from trinity → fall back to first candidate (safe default)."""
    llm = _StubLLM("not valid json {")
    cands = [
        ("First", "2020-01-01"),
        ("Second", "2021-01-01"),
    ]
    out = _trinity_select_anchor("event", cands, "Q?", llm)
    assert out == cands[0]


def test_select_anchor_no_llm_returns_none():
    """No LLM → can't run trinity, return None (skill must use other path)."""
    cands = [("First", "2020-01-01"), ("Second", "2021-01-01")]
    out = _trinity_select_anchor("event", cands, "Q?", None)
    assert out is None


def test_select_anchor_three_candidates_dimension_pick():
    """3 candidates, trinity picks the temporally-plausible one."""
    llm = _StubLLM({
        "stances": [
            {"name": "literal-match", "emphasis": "x", "conclusion": "candidate 0", "confidence": 0.6},
            {"name": "semantic-paraphrase", "emphasis": "x", "conclusion": "candidate 2", "confidence": 0.8},
            {"name": "temporal-context", "emphasis": "x", "conclusion": "candidate 2", "confidence": 0.85},
        ],
        "final_answer": "candidate 2 is best — temporal context fits",
        "confidence": 0.82,
        "chosen_index": 2,
    })
    cands = [
        ("I attended a graduation ceremony", "2024-06-01"),  # token match, but generic
        ("My friend graduated last week", "2024-05-25"),     # 3rd party
        ("I completed my Bachelor's at age 25", "2018-05-10"),  # the right one
    ]
    out = _trinity_select_anchor(
        "graduated college", cands,
        "How many years older am I than when I graduated from college?",
        llm,
    )
    assert out == cands[2]
