"""Tests for V6.4-A: candidate-entity trinity in run_open_domain_specific.

Two-stage trinity-based open-domain entity picker:
  1. LLM-as-NER extracts candidate entities from retrieved memories
  2. 3-stance trinity picks the most plausible with retry-consistency

These tests use a stub LLM that returns a programmable sequence of
canned JSON responses. The first call is the extraction; the next two
are the two trinity-consistency picks.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

def _mk_memory(content: str, mid: int = 0):
    """Create a minimal SearchResult-like object with .entry.content."""
    entry = SimpleNamespace(
        id=mid,
        content=content,
        metadata={"session_date": "2024-01-01"},
    )
    return SimpleNamespace(entry=entry, score=0.9)


class _SequenceStubLLM:
    """Returns sequential canned JSON responses across calls."""

    def __init__(self, responses: list):
        self._seq = [json.dumps(r) if isinstance(r, dict) else r for r in responses]
        self.calls = 0
        self.prompts: list[str] = []

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, system=""):
        self.prompts.append(prompt)
        idx = min(self.calls, len(self._seq) - 1)
        self.calls += 1
        r = SimpleNamespace()
        r.text = self._seq[idx]
        return r


def _trinity_pick_response(chosen_index: int) -> dict:
    return {
        "stances": [
            {"name": "evidence-direct", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "inference-bridge", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "dialog-context", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
        ],
        "final_answer": f"candidate {chosen_index}",
        "confidence": 0.85,
        "chosen_index": chosen_index,
    }


def _extract_response(candidates: list[str]) -> dict:
    return {
        "stances": [
            {"name": "literal", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "semantic", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "context", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
        ],
        "final_answer": "extracted candidates",
        "confidence": 0.85,
        "candidates": candidates,
    }


# === Direct unit tests on the helper method ===


def _make_mind_with_llm(llm):
    """Build a RadioMind-like stub exposing only what V6.4-A needs."""
    from radiomind.core.mind import RadioMind
    mind = RadioMind.__new__(RadioMind)
    mind._llm = llm
    mind._initialized = True
    return mind


def test_under_two_candidates_returns_empty():
    """0 or 1 candidate → V6.4-A returns "" (no disambiguation possible)."""
    llm = _SequenceStubLLM([_extract_response(["Acadia National Park"])])
    mind = _make_mind_with_llm(llm)
    out = mind._v64a_disambiguate_open_domain_entity(
        "Which national park did they visit?",
        [_mk_memory("We visited Acadia National Park last summer.")],
    )
    assert out == ""
    assert llm.calls == 1  # only extract called, no trinity picks


def test_consistent_pick_returns_prefix():
    """Both trinity calls return chosen_index=1 → prefix with candidate[1]."""
    llm = _SequenceStubLLM([
        _extract_response(["Acadia", "Voyageurs", "Yellowstone"]),
        _trinity_pick_response(1),
        _trinity_pick_response(1),
    ])
    mind = _make_mind_with_llm(llm)
    out = mind._v64a_disambiguate_open_domain_entity(
        "Which national park did Audrey and Andrew talk about?",
        [_mk_memory("Audrey mentioned Voyageurs being beautiful.")],
    )
    assert "ENTITY DISAMBIGUATION PICK" in out
    assert "Voyageurs" in out
    assert llm.calls == 3


def test_inconsistent_picks_falls_back():
    """Two trinity calls return different chosen_index → empty (caller falls back)."""
    llm = _SequenceStubLLM([
        _extract_response(["Acadia", "Voyageurs"]),
        _trinity_pick_response(0),
        _trinity_pick_response(1),
    ])
    mind = _make_mind_with_llm(llm)
    out = mind._v64a_disambiguate_open_domain_entity(
        "Which national park?",
        [_mk_memory("Acadia and Voyageurs both mentioned.")],
    )
    assert out == ""


def test_consistent_abstain_returns_empty():
    """Both trinity calls return chosen_index=-1 → caller falls back."""
    llm = _SequenceStubLLM([
        _extract_response(["Acadia", "Voyageurs"]),
        _trinity_pick_response(-1),
        _trinity_pick_response(-1),
    ])
    mind = _make_mind_with_llm(llm)
    out = mind._v64a_disambiguate_open_domain_entity(
        "Which national park?",
        [_mk_memory("evidence")],
    )
    assert out == ""


def test_invalid_index_falls_back():
    """Trinity returns out-of-range index → empty (defensive)."""
    llm = _SequenceStubLLM([
        _extract_response(["A", "B"]),
        _trinity_pick_response(99),
        _trinity_pick_response(99),
    ])
    mind = _make_mind_with_llm(llm)
    out = mind._v64a_disambiguate_open_domain_entity(
        "Which?", [_mk_memory("e")],
    )
    assert out == ""


def test_extraction_failure_returns_empty():
    """Extract returns no candidates list → empty."""
    llm = _SequenceStubLLM([
        {"final_answer": "no entities", "confidence": 0.3,
         "stances": [], "candidates": None},
    ])
    mind = _make_mind_with_llm(llm)
    out = mind._v64a_disambiguate_open_domain_entity(
        "Which X?", [_mk_memory("e")],
    )
    assert out == ""


def test_no_llm_returns_empty():
    """When LLM not available → no-op (caller falls back to answer_hint)."""
    class _DownLLM:
        def is_available(self): return False
        def generate(self, p, system=""): raise RuntimeError("should not call")
    mind = _make_mind_with_llm(_DownLLM())
    out = mind._v64a_disambiguate_open_domain_entity(
        "Which X?", [_mk_memory("e")],
    )
    assert out == ""


def test_unparseable_extract_returns_empty():
    """Extract returns garbage → empty."""
    llm = _SequenceStubLLM(["not valid json {"])
    mind = _make_mind_with_llm(llm)
    out = mind._v64a_disambiguate_open_domain_entity(
        "Which X?", [_mk_memory("e")],
    )
    assert out == ""
