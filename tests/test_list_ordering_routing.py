"""OrderedEventList-1d: deterministic tests for list-ordering A+B.

A — dedicated routing: `RadioMind.run_list_ordering` gates purely on
ListOrderingSkill's own trigger (no attention `wants` class needed).
B — completeness: `ListOrderingSkill.resolve` enumerates the full FACT layer
via the store when available, instead of only the top-k retrieved memories.

No LLM, no ingest: the Trinity extraction is monkeypatched to canned
instances so the routing + FACT-enumeration + sort/render logic is exercised
deterministically.
"""
from __future__ import annotations

import radiomind.skills.list_ordering as LO
from radiomind.core.mind import RadioMind

ORDER_Q = ("What is the order of the museums I visited "
           "from earliest to latest?")
NON_ORDER_Q = "When did I visit the science museum?"


class _FactEntry:          # MemoryEntry-like (bare object from list_by_domain)
    def __init__(self, content, sdate):
        self.content = content
        self.metadata = {"session_date": sdate}


class _FakeStore:
    def __init__(self, facts):
        self._facts = facts
        self.calls = []

    def list_by_domain(self, domain, level=None, limit=None):
        self.calls.append((domain, level, limit))
        return self._facts


class _FakeMind:
    def __init__(self, facts):
        self._store = _FakeStore(facts)
        self._llm = lambda *a, **k: "{}"   # truthy; never actually called here


FACTS = [
    _FactEntry("I visited the Met.", "2022/03/10 (Thu) 11:00"),
    _FactEntry("I went to the Science Museum.", "2022/01/05 (Wed) 10:00"),
    _FactEntry("Trip to the Modern Art Museum.", "2022/05/20 (Fri) 09:00"),
]


def _canned_collect(monkeypatch, capture):
    def fake(query, noun, memories, llm, max_memories=30):
        capture["memories"] = list(memories)
        capture["max"] = max_memories
        # return out of order on purpose — resolve must sort by date
        return [
            {"name": "Met", "date": "2022-03-10", "confidence": 0.9},
            {"name": "Science Museum", "date": "2022-01-05", "confidence": 0.9},
            {"name": "Modern Art Museum", "date": "2022-05-20", "confidence": 0.9},
        ]
    monkeypatch.setattr(LO, "_collect_instances_via_llm", fake)


def test_resolve_uses_fact_enumeration_and_sorts(monkeypatch):
    cap: dict = {}
    _canned_collect(monkeypatch, cap)
    mind = _FakeMind(FACTS)
    # memories=[] on purpose: only FACT enumeration can supply candidates
    res = LO.ListOrderingSkill().resolve(
        ORDER_Q, [], {"mind": mind, "domain": "d"})
    assert res is not None
    assert res.answer == "Science Museum, Met, Modern Art Museum"   # date order
    # B: the store's FACT layer was enumerated (limit 500), and the
    # candidates handed to extraction were those facts, not the empty list.
    assert mind._store.calls and mind._store.calls[0][2] == 500
    assert len(cap["memories"]) == 3
    assert cap["max"] == 500


def test_resolve_without_store_falls_back_to_memories(monkeypatch):
    cap: dict = {}
    _canned_collect(monkeypatch, cap)

    class _NoStoreMind:
        _store = None
        _llm = lambda *a, **k: "{}"

    res = LO.ListOrderingSkill().resolve(
        ORDER_Q, [{"memory": "x", "created_at": "2022/01/01 (Sat) 00:00"}],
        {"mind": _NoStoreMind(), "domain": "d"})
    assert res is not None
    assert cap["max"] == 30          # fell back to the top-k cap


def test_run_list_ordering_bypasses_non_ordering_question():
    out = RadioMind.run_list_ordering(
        _FakeMind(FACTS), NON_ORDER_Q, [], "d")
    assert out == ""                 # gate: not an ordering question


def test_run_list_ordering_fires_on_ordering_question(monkeypatch):
    _canned_collect(monkeypatch, {})
    out = RadioMind.run_list_ordering(_FakeMind(FACTS), ORDER_Q, [], "d")
    assert "STRUCTURED SKILL" in out
    assert "list_ordering" in out
