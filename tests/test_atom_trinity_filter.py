"""Tests for mind._trinity_filter_atoms — atom-level scope check.

Verifies the post-decomposition trinity that drops out-of-scope atoms
based on dimension-typed stances (literal-fit / scope-window /
relevance-strength). Ensures the filter is conservative: KEEP-by-default
unless ≥2 dimensions clearly agree an atom is out-of-scope, with edge-
case guards against over-trimming.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class _FakeAtom:
    fact: str
    count: int = 1
    confidence: float = 0.7
    evidence: tuple = ()
    kg_verified: bool = False


@pytest.fixture
def sandbox(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="rm-atomfilter-")
    monkeypatch.setenv("RADIOMIND_HOME", tmp)
    yield Path(tmp)


def _make_mind_with_canned(canned, sandbox):
    from radiomind import RadioMind
    text = canned if isinstance(canned, str) else json.dumps(canned)

    def _llm(prompt, system=""):
        return text

    m = RadioMind(llm=_llm)
    m.initialize()
    return m


def test_filter_skipped_with_few_atoms(sandbox):
    """≤2 atoms → no trinity call (filter would add noise, not signal)."""
    m = _make_mind_with_canned({
        "stances": [{"name": "x", "emphasis": "x", "conclusion": "x", "confidence": 0.7}] * 3,
        "final_answer": "x",
        "confidence": 0.8,
        "keep_atom_ids": [],
    }, sandbox)
    atoms = [_FakeAtom("hike on Saturday"), _FakeAtom("hike on Sunday")]
    out = m._trinity_filter_atoms("query", atoms)
    assert out == atoms
    m.shutdown()


def test_filter_keeps_only_in_scope(sandbox):
    """Trinity returns subset → filter applies."""
    m = _make_mind_with_canned({
        "stances": [{"name": "literal-fit", "emphasis": "x", "conclusion": "x", "confidence": 0.8}] * 3,
        "final_answer": "x",
        "confidence": 0.8,
        # Keep first 2 atoms only (consecutive weekend hikes), drop 3rd
        "keep_atom_ids": [0, 1],
    }, sandbox)
    atoms = [
        _FakeAtom("3-mile hike on Sat Mar 5"),
        _FakeAtom("5-mile hike on Sun Mar 6"),
        _FakeAtom("12-mile hike in May (out of constraint)"),
        _FakeAtom("8-mile hike on Sat Mar 12 (in following weekend)"),
    ]
    out = m._trinity_filter_atoms(
        "What's the total distance of hikes on two consecutive weekends?",
        atoms,
    )
    # Trinity returned 2 of 4 = exactly 50%. Per guard, exactly half ≥
    # max(1, 4//2)=2 — guard is "< max(1, len//2)" so 2 ≥ 2 passes.
    assert len(out) == 2
    assert all("Mar" in a.fact for a in out[:2])
    m.shutdown()


def test_filter_ignored_when_drops_more_than_half(sandbox):
    """Over-zealous filter (drops >50%) → return all atoms (safety)."""
    m = _make_mind_with_canned({
        "stances": [{"name": "x", "emphasis": "x", "conclusion": "x", "confidence": 0.8}] * 3,
        "final_answer": "x",
        "confidence": 0.8,
        "keep_atom_ids": [0],  # drops 3 of 4
    }, sandbox)
    atoms = [_FakeAtom(f"atom {i}") for i in range(4)]
    out = m._trinity_filter_atoms("query", atoms)
    # Guard kicked in: trinity dropped > 50%, so we keep all
    assert len(out) == 4
    m.shutdown()


def test_filter_ignored_on_empty_keep_list(sandbox):
    """Empty keep_atom_ids → assume bad output, return all atoms."""
    m = _make_mind_with_canned({
        "stances": [{"name": "x", "emphasis": "x", "conclusion": "x", "confidence": 0.7}] * 3,
        "final_answer": "x",
        "confidence": 0.8,
        "keep_atom_ids": [],
    }, sandbox)
    atoms = [_FakeAtom(f"atom {i}") for i in range(5)]
    out = m._trinity_filter_atoms("query", atoms)
    assert len(out) == 5
    m.shutdown()


def test_filter_ignored_on_unparseable_trinity(sandbox):
    """Bad JSON from trinity → no filter, return all."""
    m = _make_mind_with_canned("not valid json {", sandbox)
    atoms = [_FakeAtom(f"atom {i}") for i in range(5)]
    out = m._trinity_filter_atoms("query", atoms)
    assert out == atoms
    m.shutdown()


def test_filter_keeps_three_of_five_atoms(sandbox):
    """Trinity drops 2 of 5 (40%) — within safety threshold, applied."""
    m = _make_mind_with_canned({
        "stances": [{"name": "x", "emphasis": "x", "conclusion": "x", "confidence": 0.8}] * 3,
        "final_answer": "x",
        "confidence": 0.8,
        "keep_atom_ids": [0, 2, 4],
    }, sandbox)
    atoms = [_FakeAtom(f"atom {i}", count=1) for i in range(5)]
    out = m._trinity_filter_atoms("query", atoms)
    # Trinity kept 3 of 5 = 60% retention. Guard threshold "< len//2 = 2"
    # → 3 ≥ 2 passes, filter applies.
    assert len(out) == 3
    assert {a.fact for a in out} == {"atom 0", "atom 2", "atom 4"}
    m.shutdown()
