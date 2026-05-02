"""Tests for multi-round trinity debate (fractal depth).

Single-round trinity is the default; `max_rounds > 1` enables a
refinement loop where each round sees the prior round's stances and
revises. Convergence stops the loop early when:
  - all 3 stances agree (unanimous)
  - OR self-reported confidence ≥ threshold

Tests use a stateful fake LLM that returns canned trinity JSON so we
exercise the loop and convergence logic without LLM cost.
"""
from __future__ import annotations

import json
from typing import Any

from radiomind.refinement.trinity import debate


class _SequencedLLM:
    """Returns the next response from a list each time it's called."""

    def __init__(self, responses: list[dict | str]):
        self._responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, prompt: str, system: str = "") -> str:
        self.calls.append(prompt)
        if not self._responses:
            return ""
        r = self._responses.pop(0)
        return r if isinstance(r, str) else json.dumps(r)


def _stance(name: str, conclusion: str) -> dict:
    return {"name": name, "emphasis": "x", "conclusion": conclusion}


# --- Backward compatibility (max_rounds=1 default) ---

def test_default_max_rounds_is_one():
    """Default behavior: single LLM call, returns first round result."""
    llm = _SequencedLLM([{
        "stances": [_stance("a", "x"), _stance("b", "y"), _stance("c", "z")],
        "final_answer": "round-1 answer",
        "confidence": 0.4,
    }])
    result = debate("task", "evidence", llm)
    assert result is not None
    assert result["final_answer"] == "round-1 answer"
    assert len(llm.calls) == 1


def test_max_rounds_one_explicit():
    """max_rounds=1 is identical to default."""
    llm = _SequencedLLM([{
        "stances": [_stance("a", "x"), _stance("b", "y"), _stance("c", "z")],
        "final_answer": "single",
        "confidence": 0.3,
    }])
    result = debate("task", "evidence", llm, max_rounds=1)
    assert result["final_answer"] == "single"
    assert len(llm.calls) == 1


def test_round_1_failure_returns_none():
    """Bad JSON in round 1 → None (legacy behavior)."""
    llm = _SequencedLLM(["not json {"])
    result = debate("task", "evidence", llm, max_rounds=3)
    assert result is None


# --- Multi-round refinement ---

def test_multi_round_runs_until_max_rounds_when_no_convergence():
    """3 rounds of low-confidence non-unanimous → 3 LLM calls."""
    rsp = lambda final, conf: {
        "stances": [_stance("a", "alpha"), _stance("b", "beta"), _stance("c", "gamma")],
        "final_answer": final,
        "confidence": conf,
    }
    llm = _SequencedLLM([
        rsp("round-1", 0.4),
        rsp("round-2", 0.5),
        rsp("round-3", 0.6),
    ])
    result = debate("task", "evidence", llm, max_rounds=3)
    assert result["final_answer"] == "round-3"
    assert len(llm.calls) == 3


def test_multi_round_stops_on_high_confidence():
    """Round 2 hits confidence ≥ threshold → stops; round 3 not called."""
    llm = _SequencedLLM([
        {
            "stances": [_stance("a", "alpha"), _stance("b", "beta"), _stance("c", "gamma")],
            "final_answer": "round-1",
            "confidence": 0.4,
        },
        {
            "stances": [_stance("a", "alpha"), _stance("b", "beta"), _stance("c", "gamma")],
            "final_answer": "round-2-converged",
            "confidence": 0.85,  # above default threshold 0.7
        },
        # never reached
    ])
    result = debate("task", "evidence", llm, max_rounds=5)
    assert result["final_answer"] == "round-2-converged"
    assert len(llm.calls) == 2


def test_multi_round_stops_on_unanimous_stances():
    """All 3 stances agree → converged, even if confidence is low."""
    llm = _SequencedLLM([
        {
            "stances": [_stance("a", "X"), _stance("b", "Y"), _stance("c", "Z")],
            "final_answer": "round-1",
            "confidence": 0.3,
        },
        {
            "stances": [_stance("a", "agreed"), _stance("b", "agreed"), _stance("c", "agreed")],
            "final_answer": "round-2-unanimous",
            "confidence": 0.4,
        },
        # never reached — unanimous triggers stop
    ])
    result = debate("task", "evidence", llm, max_rounds=5)
    assert result["final_answer"] == "round-2-unanimous"
    assert len(llm.calls) == 2


def test_refinement_round_failure_keeps_prior_result():
    """If a refinement round returns garbage, keep the previous round's result."""
    llm = _SequencedLLM([
        {
            "stances": [_stance("a", "x"), _stance("b", "y"), _stance("c", "z")],
            "final_answer": "round-1-good",
            "confidence": 0.4,
        },
        "not parseable {",  # round 2 fails
        "still bad",         # round 3 fails
    ])
    result = debate("task", "evidence", llm, max_rounds=3)
    assert result["final_answer"] == "round-1-good"
    # All 3 attempts made (we keep going through max_rounds even on failure)
    assert len(llm.calls) == 3


def test_converge_threshold_can_be_loosened():
    """Custom threshold 0.5 → confidence 0.6 stops the loop."""
    llm = _SequencedLLM([
        {
            "stances": [_stance("a", "x"), _stance("b", "y"), _stance("c", "z")],
            "final_answer": "first",
            "confidence": 0.6,
        },
    ])
    result = debate("task", "evidence", llm, max_rounds=3, converge_threshold=0.5)
    # Round 1 has confidence 0.6 ≥ threshold 0.5 → BUT we always run round 1
    # then check convergence before round 2. Round 1 returns immediately
    # because max_rounds check is `if max_rounds <= 1` first; here we go
    # into the loop, immediately converge, and return after round 1.
    assert result["final_answer"] == "first"
    assert len(llm.calls) == 1


def test_n_stances_parameter_changes_prompt():
    """n_stances=4 → prompt asks for 4 stances + 4 stance slots."""
    llm = _SequencedLLM([{
        "stances": [_stance(f"s{i}", "x") for i in range(4)],
        "final_answer": "4-party",
        "confidence": 0.8,
    }])
    result = debate("task", "evidence", llm, n_stances=4)
    assert result["final_answer"] == "4-party"
    # Prompt should reflect the count
    assert "4 distinct opposing stances" in llm.calls[0]


def test_n_stances_clamped_to_range():
    """n_stances clamped to [2, 7]; values outside snap to bounds."""
    llm = _SequencedLLM([{
        "stances": [_stance("a", "x"), _stance("b", "y")],
        "final_answer": "2-stance",
        "confidence": 0.8,
    }])
    # n_stances=1 should clamp to 2
    result = debate("task", "evidence", llm, n_stances=1)
    assert result is not None
    assert "2 distinct opposing stances" in llm.calls[0]


def test_sub_trinity_recursion_low_confidence_stance():
    """sub_trinity_depth=1 + a stance with confidence < 0.5 → spawns inner debate."""
    # Outer round 1: stance "uncertain" has confidence 0.3 → triggers recursion
    outer_round1 = {
        "stances": [
            {"name": "confident", "emphasis": "x", "conclusion": "A", "confidence": 0.9},
            {"name": "uncertain", "emphasis": "y", "conclusion": "MAYBE B", "confidence": 0.3},
            {"name": "skeptic", "emphasis": "z", "conclusion": "C", "confidence": 0.8},
        ],
        "final_answer": "tentative",
        "confidence": 0.6,
    }
    # Inner debate for the "uncertain" stance — converges to a refined answer
    inner_debate = {
        "stances": [
            _stance("literal", "B confirmed"),
            _stance("inference", "B confirmed"),
            _stance("skeptic", "B confirmed"),
        ],
        "final_answer": "REFINED B",
        "confidence": 0.85,
    }
    llm = _SequencedLLM([outer_round1, inner_debate])
    result = debate("task", "evidence", llm, sub_trinity_depth=1)
    assert result is not None
    # The "uncertain" stance's conclusion should now be the inner answer
    uncertain_stance = next(
        s for s in result["stances"] if s["name"] == "uncertain"
    )
    assert uncertain_stance["conclusion"] == "REFINED B"
    assert uncertain_stance["confidence"] == 0.85
    # Provenance recorded on outer + stance
    assert any("sub_trinity_depth=" in p for p in result.get("provenance", []))
    assert "sub_trinity" in (uncertain_stance.get("provenance") or [])
    # Two LLM calls: outer + 1 inner (only 1 stance was weak)
    assert len(llm.calls) == 2


def test_sub_trinity_skipped_when_all_stances_confident():
    """When every stance has confidence ≥ threshold → no recursion."""
    llm = _SequencedLLM([{
        "stances": [
            {"name": "a", "emphasis": "x", "conclusion": "A", "confidence": 0.8},
            {"name": "b", "emphasis": "y", "conclusion": "B", "confidence": 0.7},
            {"name": "c", "emphasis": "z", "conclusion": "C", "confidence": 0.9},
        ],
        "final_answer": "ok",
        "confidence": 0.8,
    }])
    result = debate("task", "evidence", llm, sub_trinity_depth=1)
    assert result is not None
    assert len(llm.calls) == 1  # No inner debate fired


def test_profile_fast_is_single_round():
    from radiomind.refinement.trinity import fast
    llm = _SequencedLLM([{
        "stances": [_stance("a", "x"), _stance("b", "y"), _stance("c", "z")],
        "final_answer": "fast",
        "confidence": 0.4,
    }])
    result = fast("task", "evidence", llm)
    assert result["final_answer"] == "fast"
    assert len(llm.calls) == 1


def test_profile_balanced_is_two_rounds():
    from radiomind.refinement.trinity import balanced
    rsp = lambda f, c: {
        "stances": [_stance("a", "x"), _stance("b", "y"), _stance("c", "z")],
        "final_answer": f, "confidence": c,
    }
    # Round 1 low-conf, round 2 high-conf converges
    llm = _SequencedLLM([rsp("r1", 0.4), rsp("r2", 0.85)])
    result = balanced("task", "evidence", llm)
    assert result["final_answer"] == "r2"
    assert len(llm.calls) == 2


def test_profile_parties_uses_n_stances():
    from radiomind.refinement.trinity import parties
    llm = _SequencedLLM([{
        "stances": [_stance(f"s{i}", "x") for i in range(5)],
        "final_answer": "5-party",
        "confidence": 0.85,
    }])
    result = parties(5, "task", "evidence", llm)
    assert result["final_answer"] == "5-party"
    assert "5 distinct opposing stances" in llm.calls[0]


def test_refinement_prompt_includes_prior_stances():
    """Round 2's prompt should contain prior round's stance content."""
    llm = _SequencedLLM([
        {
            "stances": [
                _stance("frequency", "Met is most-mentioned"),
                _stance("context", "City Art is contextual"),
                _stance("attribute", "ambiguous"),
            ],
            "final_answer": "Metropolitan",
            "confidence": 0.4,
        },
        {
            "stances": [_stance("a", "x"), _stance("b", "y"), _stance("c", "z")],
            "final_answer": "refined",
            "confidence": 0.85,
        },
    ])
    result = debate("task", "evidence", llm, max_rounds=2)
    assert result["final_answer"] == "refined"
    # Round 2 prompt should mention round 1's content
    round_2_prompt = llm.calls[1]
    assert "REFINEMENT ROUND 2" in round_2_prompt
    assert "Metropolitan" in round_2_prompt
    assert "frequency" in round_2_prompt
    assert "Met is most-mentioned" in round_2_prompt
