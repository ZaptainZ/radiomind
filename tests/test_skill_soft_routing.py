"""Tests for try_resolve_soft (GAP-3) — multi-skill trinity vote routing.

Hard routing (try_resolve) takes the first matching skill's result.
Soft routing collects ALL matching skills' results and uses trinity to
pick the best. Tests verify the fall-back behaviour and the trinity
vote path with a mocked LLM.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from radiomind.skills.base import Skill, SkillResult


@dataclass
class _SigStub:
    wants: str = "lookup"
    aux_flags: dict | None = None


class _MockSkillAlwaysMatch(Skill):
    name = "mock-A"
    priority = 50

    def __init__(self, answer: str = "from-A", confidence: float = 0.7):
        self._answer = answer
        self._conf = confidence

    def match(self, signature) -> bool:
        return True

    def resolve(self, query, memories, context):
        return SkillResult(
            skill_name=self.name, answer=self._answer,
            anchors=[("from", "A")], confidence=self._conf,
        )


class _MockSkillNeverMatch(Skill):
    name = "mock-B"
    priority = 60

    def match(self, signature) -> bool:
        return False

    def resolve(self, query, memories, context):
        return None


class _MockSkillMatchNoResult(Skill):
    name = "mock-C"
    priority = 70

    def match(self, signature) -> bool:
        return True

    def resolve(self, query, memories, context):
        return None


class _MockLLM:
    """Returns canned trinity JSON for the chosen_index vote."""

    def __init__(self, canned_json: dict | str):
        self._text = (canned_json if isinstance(canned_json, str)
                       else json.dumps(canned_json))

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, system=""):
        class _R:
            pass
        r = _R()
        r.text = self._text
        return r


def _patched_registry(monkeypatch, skills):
    """Replace REGISTRY with the given skills for one test."""
    from radiomind.skills import registry
    monkeypatch.setattr(registry, "REGISTRY", list(skills))
    return registry


def test_zero_candidates_returns_none(monkeypatch):
    reg = _patched_registry(monkeypatch, [_MockSkillNeverMatch()])
    out = reg.try_resolve_soft("Q", [], _SigStub(), {})
    assert out is None


def test_single_candidate_returned_directly(monkeypatch):
    skill = _MockSkillAlwaysMatch(answer="solo", confidence=0.9)
    reg = _patched_registry(monkeypatch, [skill])
    out = reg.try_resolve_soft("Q", [], _SigStub(), {})
    assert out is not None
    assert out.skill_name == "mock-A"
    assert out.answer == "solo"


def test_multi_candidates_no_llm_fallback_to_max_confidence(monkeypatch):
    """No LLM in context → fall back to highest-confidence candidate."""
    s1 = _MockSkillAlwaysMatch(answer="low", confidence=0.4)
    s1.name = "low-skill"
    s2 = _MockSkillAlwaysMatch(answer="high", confidence=0.9)
    s2.name = "high-skill"
    reg = _patched_registry(monkeypatch, [s1, s2])
    out = reg.try_resolve_soft("Q", [], _SigStub(), {"mind": None})
    assert out is not None
    assert out.skill_name == "high-skill"


def test_multi_candidates_trinity_vote_picks_chosen_index(monkeypatch):
    """Trinity returns chosen_index=1 → second skill's result wins."""
    s1 = _MockSkillAlwaysMatch(answer="first", confidence=0.5)
    s1.name = "first-skill"
    s2 = _MockSkillAlwaysMatch(answer="second", confidence=0.4)
    s2.name = "second-skill"
    reg = _patched_registry(monkeypatch, [s1, s2])

    class _MindStub:
        _llm = _MockLLM({
            "stances": [{"name": "x", "emphasis": "x", "conclusion": "x"}] * 3,
            "final_answer": "second is better",
            "chosen_index": 1,
        })

    out = reg.try_resolve_soft("Q", [], _SigStub(), {"mind": _MindStub()})
    assert out is not None
    assert out.skill_name == "second-skill"
    assert out.answer == "second"


def test_multi_candidates_trinity_unparseable_falls_back(monkeypatch):
    """Trinity returns garbage → fall back to highest-confidence."""
    s1 = _MockSkillAlwaysMatch(answer="conf-high", confidence=0.95)
    s1.name = "high"
    s2 = _MockSkillAlwaysMatch(answer="conf-low", confidence=0.3)
    s2.name = "low"
    reg = _patched_registry(monkeypatch, [s1, s2])

    class _MindStub:
        _llm = _MockLLM("not valid json {")

    out = reg.try_resolve_soft("Q", [], _SigStub(), {"mind": _MindStub()})
    assert out is not None
    assert out.skill_name == "high"  # max confidence wins


def test_multi_candidates_trinity_index_out_of_range(monkeypatch):
    """Trinity returns chosen_index out of range → fall back to max conf."""
    s1 = _MockSkillAlwaysMatch(answer="A", confidence=0.6)
    s1.name = "alpha"
    s2 = _MockSkillAlwaysMatch(answer="B", confidence=0.8)
    s2.name = "beta"
    reg = _patched_registry(monkeypatch, [s1, s2])

    class _MindStub:
        _llm = _MockLLM({
            "stances": [{"name": "x", "emphasis": "x", "conclusion": "x"}] * 3,
            "final_answer": "x",
            "chosen_index": 99,  # invalid
        })

    out = reg.try_resolve_soft("Q", [], _SigStub(), {"mind": _MindStub()})
    assert out is not None
    assert out.skill_name == "beta"  # max confidence wins
