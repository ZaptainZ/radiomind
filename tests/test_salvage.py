"""Tests for BidirectionalAbstainGate (trinity-based abstain decision).

The gate must:
  1. Default to KEEP when retrieval is empty (cannot second-guess).
  2. Default to KEEP when trinity returns no parseable verdict.
  3. Override to ABSTAIN when trinity decision = "abstain".
  4. Override to REWRITE when trinity decision = "rewrite" + new text.
  5. Fall back to KEEP when "rewrite" decided but no rewritten text given.
  6. Be symmetric: works on both abstained drafts and confident drafts.

Tests use a fake LLM that returns canned trinity JSON, so we exercise
the gate's logic without LLM costs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from radiomind.refinement.salvage import (
    BidirectionalAbstainGate,
    GateResult,
    looks_abstained,
)


@dataclass
class _FakeEntry:
    id: int
    content: str
    metadata: dict


@dataclass
class _FakeSearchResult:
    entry: _FakeEntry
    score: float = 1.0


def _mem(content: str, turn_id: str = "t1") -> _FakeSearchResult:
    return _FakeSearchResult(
        entry=_FakeEntry(id=1, content=content, metadata={"turn_id": turn_id})
    )


def _make_gate(canned_response: dict | str) -> BidirectionalAbstainGate:
    """Build a gate whose LLM returns the given canned trinity JSON."""
    text = canned_response if isinstance(canned_response, str) else json.dumps(canned_response)

    def _fake_llm(prompt: str, system: str) -> str:
        return text

    return BidirectionalAbstainGate(_fake_llm)


def test_no_memories_returns_none():
    """Gate cannot review without retrieved memories."""
    gate = _make_gate({"final_answer": "x", "decision": "abstain", "stances": []})
    result = gate.review("Q?", "An answer", retrieved=[])
    assert result is None


def test_empty_draft_returns_none():
    """Gate cannot review an empty draft."""
    gate = _make_gate({"final_answer": "x", "decision": "abstain", "stances": []})
    result = gate.review("Q?", "", retrieved=[_mem("foo")])
    assert result is None


def test_trinity_unparseable_returns_none():
    """When trinity output is not valid JSON, gate returns None (= keep)."""
    gate = _make_gate("not json at all {invalid")
    result = gate.review("Q?", "An answer", retrieved=[_mem("foo")])
    assert result is None


def test_confident_draft_skips_gate_entirely():
    """REGRESSION GUARD (n=100 v4 lesson): the gate must NOT touch
    confident drafts. Running trinity on every draft caused systematic
    over-abstain (7/10 v3→v4 regressions). The gate is under-confidence
    only — confident drafts pass through unchanged.
    """
    gate = _make_gate({
        "stances": [{"name": "Strict", "emphasis": "x", "conclusion": "abstain"}],
        "final_answer": "memories don't support",
        "decision": "abstain",
        "confidence": 0.95,
    })
    # Even with trinity primed to say "abstain", a confident draft
    # MUST short-circuit before trinity runs.
    result = gate.review(
        "What's my favorite color?",
        "Your favorite color is blue.",
        retrieved=[_mem("user said favorite color is blue")],
    )
    assert result is None


def test_keep_when_abstained_draft_should_remain_abstained():
    """Under-confidence path: model abstained, trinity says keep → return keep."""
    gate = _make_gate({
        "stances": [{"name": "Literal", "emphasis": "x", "conclusion": "support"}],
        "final_answer": "draft is fine",
        "decision": "keep",
        "confidence": 0.7,
    })
    draft = "The information provided is not enough."
    assert looks_abstained(draft)
    result = gate.review("Q?", draft, retrieved=[_mem("foo")])
    assert result is not None
    assert result.action == "keep"
    assert result.answer == draft


def test_rewrite_replaces_under_confidence_abstain():
    """Under-confidence path with rewrite decision: replace abstain text
    with trinity's hedged answer. Targets gpt4_d12ceb0e-style cases
    where memories support a partial answer (range / inferable midpoint)
    but the model bailed."""
    gate = _make_gate({
        "stances": [{"name": "Range", "emphasis": "x", "conclusion": "midpoint"}],
        "final_answer": "use range midpoint",
        "decision": "rewrite",
        "rewritten_answer": "Approximately 60-65 years old (parents in their early 30s when user was born).",
        "confidence": 0.75,
    })
    result = gate.review(
        "What's my parents' age?",
        "The information provided is not enough.",
        retrieved=[_mem("parents were in their early 30s when had me; user is 32")],
    )
    assert result is not None
    assert result.action == "rewrite"
    assert "60-65" in result.answer


def test_rewrite_without_text_falls_back_to_keep():
    """Trinity says rewrite but gives no rewritten_answer → keep abstain draft."""
    gate = _make_gate({
        "stances": [{"name": "x", "emphasis": "x", "conclusion": "x"}],
        "final_answer": "no rewrite text",
        "decision": "rewrite",
        "rewritten_answer": "",
        "confidence": 0.5,
    })
    abstained_draft = "The information provided is not enough."
    result = gate.review("Q?", abstained_draft, retrieved=[_mem("foo")])
    assert result is not None
    assert result.action == "keep"
    assert result.answer == abstained_draft


def test_commit_overrides_under_confidence_abstain():
    """Trinity decision=abstain on an already-abstain draft is a no-op
    (keep). But when abstain markers in draft + trinity says commit
    via rewrite or keeps as keep — the salvage either rewrites with new
    text or leaves the abstain in place. Cover the explicit abstain
    decision against an abstain draft (rare but defined: keep abstain).
    """
    gate = _make_gate({
        "stances": [{"name": "Strict", "emphasis": "x", "conclusion": "abstain"}],
        "final_answer": "stays abstain",
        "decision": "abstain",
        "confidence": 0.85,
    })
    abstained_draft = "The information provided is not enough."
    result = gate.review("Q?", abstained_draft, retrieved=[_mem("evidence")])
    assert result is not None
    assert result.action == "abstain"
    assert result.answer == "The information provided is not enough."


def test_unknown_decision_treated_as_keep():
    """Defensive: unknown decision string → keep abstain draft unchanged."""
    gate = _make_gate({
        "stances": [{"name": "x", "emphasis": "x", "conclusion": "x"}],
        "final_answer": "garbled",
        "decision": "xyzzy",
        "confidence": 0.5,
    })
    abstained_draft = "The information provided is not enough."
    result = gate.review("Q?", abstained_draft, retrieved=[_mem("foo")])
    assert result is not None
    assert result.action == "keep"
    assert result.answer == abstained_draft
