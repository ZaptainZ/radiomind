"""Tests for mind.run_entity_disambiguation (GAP-6).

When a question uses a definite reference ("the museum") and retrieved
memories contain multiple candidate entities of that type, trinity
votes which one is intended. The bench harness injects the chosen
entity as a prompt prefix.

Tests use a fake LLM returning canned trinity JSON, so we exercise
the disambiguation logic without LLM costs.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest


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


@pytest.fixture
def sandbox(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="rm-entitydisamb-")
    monkeypatch.setenv("RADIOMIND_HOME", tmp)
    yield Path(tmp)


def _make_mind(canned_trinity_response: dict | str | None, sandbox):
    """RadioMind with a fake LLM returning canned trinity JSON."""
    from radiomind import RadioMind

    text = (canned_trinity_response if isinstance(canned_trinity_response, str)
            else json.dumps(canned_trinity_response or {}))

    def _fake_llm(prompt, system=""):
        return text

    m = RadioMind(llm=_fake_llm)
    m.initialize()
    return m


def test_returns_empty_when_no_definite_reference(sandbox):
    m = _make_mind({"final_answer": "x"}, sandbox)
    out = m.run_entity_disambiguation(
        "How many guitars do I own?",
        retrieved_memories=[_mem("I have a Fender Stratocaster")],
    )
    assert out == ""
    m.shutdown()


def test_returns_empty_when_only_one_candidate(sandbox):
    m = _make_mind({"final_answer": "x"}, sandbox)
    out = m.run_entity_disambiguation(
        "When did I visit the museum?",
        retrieved_memories=[_mem("I went to the Metropolitan Museum on March 5")],
    )
    # Only one museum candidate → no disambiguation needed
    assert out == ""
    m.shutdown()


def test_disambiguates_between_multiple_museums(sandbox):
    m = _make_mind({
        "stances": [
            {"name": "frequency", "emphasis": "x", "conclusion": "Met"},
            {"name": "context", "emphasis": "x", "conclusion": "Met"},
            {"name": "attribute", "emphasis": "x", "conclusion": "Met"},
        ],
        "final_answer": "Metropolitan Museum chosen",
        "chosen_candidate": "Metropolitan Museum",
        "confidence": 0.85,
    }, sandbox)
    out = m.run_entity_disambiguation(
        "What time was the museum exhibit on Ancient Civilizations held?",
        retrieved_memories=[
            _mem("I visited the Metropolitan Museum to see the Ancient Civilizations exhibit on March 10"),
            _mem("I went to the City Art Museum yesterday for the modern art show"),
            _mem("Last weekend's trip included the Metropolitan Museum's Egyptian wing"),
            _mem("The City Art Museum had a free admission day in February"),
        ],
    )
    assert out, "expected disambiguation prefix"
    assert "Metropolitan Museum" in out
    assert "City Art Museum" not in out  # rejected candidate
    m.shutdown()


def test_returns_empty_when_trinity_picks_unknown_candidate(sandbox):
    """Defensive: if trinity returns a name we never saw, ignore it."""
    m = _make_mind({
        "final_answer": "garbled",
        "chosen_candidate": "Made Up Museum That Wasn't In Memories",
        "confidence": 0.3,
    }, sandbox)
    out = m.run_entity_disambiguation(
        "what time did the museum open?",
        retrieved_memories=[
            _mem("The Metropolitan Museum opens at 10am"),
            _mem("The City Art Museum is closed Mondays"),
        ],
    )
    # Trinity's output isn't a real candidate → gate refuses to inject.
    assert out == ""
    m.shutdown()


def test_returns_empty_when_trinity_unparseable(sandbox):
    """When trinity output is bad JSON, gate stays silent (no override)."""
    m = _make_mind("not json at all {invalid", sandbox)
    out = m.run_entity_disambiguation(
        "what time did the museum open?",
        retrieved_memories=[
            _mem("The Metropolitan Museum opens at 10am"),
            _mem("The City Art Museum is closed Mondays"),
        ],
    )
    assert out == ""
    m.shutdown()


def test_disambiguates_anaphoric_reference(sandbox):
    """Question uses 'where was that event held' (anaphoric, no
    definite-article 'the museum'). Detection should still trigger
    on venue-suffix candidates in memories. Targets gpt4_59149c78
    where the failure was a missing detection on 'that event'.
    """
    m = _make_mind({
        "stances": [
            {"name": "frequency", "emphasis": "x", "conclusion": "Met"},
            {"name": "context", "emphasis": "x", "conclusion": "Met"},
            {"name": "attribute", "emphasis": "x", "conclusion": "Met"},
        ],
        "final_answer": "Metropolitan chosen",
        "chosen_candidate": "Metropolitan Museum",
        "confidence": 0.85,
    }, sandbox)
    out = m.run_entity_disambiguation(
        "I participated in an art event two weeks ago. Where was that "
        "event held?",
        retrieved_memories=[
            _mem("I went to the Metropolitan Museum's art exhibit on Jan 18"),
            _mem("Last month I visited the City Art Museum"),
            _mem("The Metropolitan Museum's modern wing was closed yesterday"),
            _mem("I had coffee near the City Art Museum on Saturday"),
        ],
    )
    assert out, "expected anaphoric disambiguation prefix"
    assert "Metropolitan Museum" in out
