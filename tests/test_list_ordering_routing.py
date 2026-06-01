"""OrderedEventList-1d/1f: deterministic tests for list-ordering.

A — routing: `RadioMind.run_list_ordering` gates on the skill's own trigger.
B — completeness: `resolve` enumerates the full FACT layer when available.
1f — extraction mechanics: relevance filter -> chunked extraction ->
     merge/dedup -> sort. No LLM, no ingest (extraction is monkeypatched).
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


def _patch_collect(monkeypatch, capture):
    def fake(query, noun, memories, llm, max_memories=200):
        capture["memories"] = list(memories)
        return [   # out of order on purpose — resolve must sort by date
            {"name": "Met", "date": "2022-03-10", "confidence": 0.9},
            {"name": "Science Museum", "date": "2022-01-05", "confidence": 0.9},
            {"name": "Modern Art Museum", "date": "2022-05-20", "confidence": 0.9},
        ]
    monkeypatch.setattr(LO, "_collect_instances_via_llm", fake)


# ---- B + pipeline (resolve) ----
def test_resolve_fact_enum_filter_and_sorts(monkeypatch):
    cap: dict = {}
    _patch_collect(monkeypatch, cap)
    mind = _FakeMind(FACTS)
    res = LO.ListOrderingSkill().resolve(ORDER_Q, [], {"mind": mind, "domain": "d"})
    assert res is not None
    assert res.answer == "Science Museum, Met, Modern Art Museum"   # date order
    assert mind._store.calls and mind._store.calls[0][2] == 500     # FACT enum
    # the relevance-filtered facts reached extraction (all 3 are museum facts)
    assert len(cap["memories"]) == 3


def test_resolve_without_store_uses_memories(monkeypatch):
    cap: dict = {}
    _patch_collect(monkeypatch, cap)

    class _NoStoreMind:
        _store = None
        _llm = lambda *a, **k: "{}"

    res = LO.ListOrderingSkill().resolve(
        ORDER_Q,
        [{"memory": "I went to the Science Museum.",
          "created_at": "2022/01/01 (Sat) 00:00"}],
        {"mind": _NoStoreMind(), "domain": "d"})
    assert res is not None      # falls back to the passed-in memories


# ---- A — routing ----
def test_run_list_ordering_bypasses_non_ordering_question():
    out = RadioMind.run_list_ordering(_FakeMind(FACTS), NON_ORDER_Q, [], "d")
    assert out == ""


def test_run_list_ordering_fires_on_ordering_question(monkeypatch):
    _patch_collect(monkeypatch, {})
    out = RadioMind.run_list_ordering(_FakeMind(FACTS), ORDER_Q, [], "d")
    assert "STRUCTURED SKILL" in out
    assert "list_ordering" in out


# ---- 1f mechanics (pure, deterministic) ----
def test_relevant_facts_singular_and_plural():
    facts = [
        _FactEntry("I visited the Science Museum.", "d1"),     # singular
        _FactEntry("Bought groceries at the store.", "d2"),    # irrelevant
        _FactEntry("Trip to the museums downtown.", "d3"),     # plural
    ]
    out = LO._relevant_facts(facts, "the six museums I visited")
    contents = [f.content for f in out]
    assert any("Science Museum" in c for c in contents)
    assert any("museums downtown" in c for c in contents)
    assert all("groceries" not in c for c in contents)


def test_chunks_splits_by_size():
    assert LO._chunks([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_collect_extracts_every_chunk(monkeypatch):
    seen: list[int] = []

    def fake_extract(query, noun, chunk, llm):
        seen.append(len(chunk))
        return [{"name": f"x{len(seen)}",
                 "date": f"2022-01-{len(seen):02d}", "confidence": 0.9}]

    monkeypatch.setattr(LO, "_extract_chunk", fake_extract)
    out = LO._collect_instances_via_llm(
        "q", "noun", list(range(25)), llm=lambda *a, **k: "{}")
    assert seen == [10, 10, 5]      # all chunks, correct sizes
    assert len(out) == 3            # one instance per chunk, concatenated


def test_merge_dedup_collapses_and_keeps_earliest():
    out = LO._merge_dedup([
        {"name": "The Met", "date": "2022-03-10", "confidence": 0.9},
        {"name": "Met", "date": "2022-01-05", "confidence": 0.8},   # dup, earlier
        {"name": "Science Museum", "date": "2022-02-01", "confidence": 0.9},
    ])
    keys = sorted(LO._norm_name(i["name"]) for i in out)
    assert keys == ["met", "science museum"]            # collapsed to 2
    met = [i for i in out if LO._norm_name(i["name"]) == "met"][0]
    assert met["date"] == "2022-01-05"                  # earliest kept
