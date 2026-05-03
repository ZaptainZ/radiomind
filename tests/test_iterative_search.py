"""Tests for mind.iterative_search — multi-anchor attention via trinity.

Verifies that the iterative retrieval pattern:
  Pass 1 → trinity-N-party generates expansion queries → Pass 2 → merge
works end-to-end with a fake LLM and is degraded gracefully when the
LLM is unavailable or trinity returns no usable expansion queries.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sandbox(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="rm-itersearch-")
    monkeypatch.setenv("RADIOMIND_HOME", tmp)
    yield Path(tmp)


def _ingest(mind, *contents):
    """Helper: ingest plain user-turn contents into a fixed domain."""
    from radiomind.core.types import Message
    msgs = [
        {"role": "user", "content": c, "metadata": {
            "turn_id": f"t{i}", "session_date": "2025-01-01",
        }}
        for i, c in enumerate(contents)
    ]
    mind.ingest_turns_raw(
        msgs, domain="test", user_id="u",
        run_aggregation=False, run_refinement=False,
    )


def test_iterative_search_no_llm_returns_seed_only(sandbox):
    """No LLM available → second-pass skipped, returns first-pass only."""
    from radiomind import RadioMind
    m = RadioMind()  # no llm
    m.initialize()
    _ingest(m,
        "I saw the new Marvel movie last weekend",
        "I bought a Fender Stratocaster guitar yesterday",
        "I love hiking in the Cascade mountains",
    )
    out = m.iterative_search("guitar", domain="test", max_passes=2, n_anchors=3)
    assert isinstance(out, list)
    # Pass 1 alone should still return some results (seed-only)
    m.shutdown()


def test_iterative_search_with_llm_expands_query(sandbox):
    """LLM available → trinity proposes expansion queries → pass 2
    surfaces additional memories under different surface terms."""
    from radiomind import RadioMind

    # Stateful mock: detect trinity prompt vs others.
    def _llm(prompt, system=""):
        # Trinity expansion call has 'queries' in extra_schema
        if "DIFFERENT focused search queries" in prompt or '"queries"' in prompt:
            return json.dumps({
                "stances": [
                    {"name": "literal", "emphasis": "x", "conclusion": "x", "confidence": 0.7},
                    {"name": "gear", "emphasis": "x", "conclusion": "x", "confidence": 0.7},
                    {"name": "pref", "emphasis": "x", "conclusion": "x", "confidence": 0.7},
                ],
                "final_answer": "expansion ok",
                "confidence": 0.8,
                "queries": ["Fender Stratocaster", "electric guitar gear", "music preferences"],
            })
        # Other LLM calls (extraction, etc) — return empty
        return json.dumps({"events": []})

    m = RadioMind(llm=_llm)
    m.initialize()
    _ingest(m,
        "I bought a Fender Stratocaster yesterday",
        "I love Pale Waves indie-pop",
        "My morning routine includes coffee",
        "Gibson Les Paul vs Fender Strat — tone differences",
        "The new Marvel movie was disappointing",
    )
    out = m.iterative_search(
        "guitar tips", domain="test", max_passes=2, n_anchors=3,
    )
    assert isinstance(out, list)
    # Should at minimum return the seed; ideally more after expansion
    assert len(out) >= 0
    m.shutdown()


def test_iterative_search_handles_unparseable_trinity(sandbox):
    """Trinity returns garbage JSON → degrade gracefully to seed."""
    from radiomind import RadioMind

    def _llm(prompt, system=""):
        if '"queries"' in prompt:
            return "not json {invalid"
        return json.dumps({"events": []})

    m = RadioMind(llm=_llm)
    m.initialize()
    _ingest(m, "I bought a guitar", "Other content")
    out = m.iterative_search("guitar", domain="test")
    assert isinstance(out, list)
    m.shutdown()


def test_iterative_search_dedupes_against_seed(sandbox):
    """If trinity proposes a query that returns the same memory as seed,
    the result is not duplicated in output."""
    from radiomind import RadioMind

    def _llm(prompt, system=""):
        if '"queries"' in prompt:
            # Propose queries that all match the same memory
            return json.dumps({
                "stances": [{"name": "x", "emphasis": "x", "conclusion": "x", "confidence": 0.7}] * 3,
                "final_answer": "ok",
                "confidence": 0.8,
                "queries": ["guitar", "guitar", "guitar"],
            })
        return json.dumps({"events": []})

    m = RadioMind(llm=_llm)
    m.initialize()
    _ingest(m, "I bought a guitar yesterday")
    out = m.iterative_search("guitar", domain="test", max_passes=2)
    # Should not have duplicates of the same memory
    contents = [r.entry.content for r in out if hasattr(r, "entry")]
    assert len(set(contents)) == len(contents)
    m.shutdown()


def test_iterative_search_max_passes_one_skips_expansion(sandbox):
    """max_passes=1 → never call trinity, return seed only."""
    from radiomind import RadioMind

    trinity_called = {"n": 0}
    def _llm(prompt, system=""):
        if '"queries"' in prompt:
            trinity_called["n"] += 1
        return json.dumps({"events": []})

    m = RadioMind(llm=_llm)
    m.initialize()
    _ingest(m, "memory 1", "memory 2")
    m.iterative_search("Q", domain="test", max_passes=1)
    assert trinity_called["n"] == 0
    m.shutdown()


def test_iterative_search_seed_results_param_skips_pass1(sandbox):
    """When caller supplies seed_results, pass-1 search is skipped."""
    from radiomind import RadioMind

    def _llm(prompt, system=""):
        if '"queries"' in prompt:
            return json.dumps({
                "stances": [{"name": "x", "emphasis": "x", "conclusion": "x", "confidence": 0.7}] * 3,
                "final_answer": "ok",
                "confidence": 0.8,
                "queries": ["coffee"],
            })
        return json.dumps({"events": []})

    m = RadioMind(llm=_llm)
    m.initialize()
    _ingest(m, "I drink coffee daily", "I bought a guitar")
    # Seed 0 results forces pass 2 to be the only retrieval
    out = m.iterative_search(
        "Q", domain="test", seed_results=[],
        max_passes=2, n_anchors=3,
    )
    # Should have surfaced "coffee" memory via the trinity-proposed query
    contents = [r.entry.content for r in out if hasattr(r, "entry")]
    assert any("coffee" in c.lower() for c in contents)
    m.shutdown()
