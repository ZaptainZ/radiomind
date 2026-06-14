"""BioLocalRetrieval-1b: typed-facet rerank for the FTS-only bare-install path.

Covers the pure module (gate + scoring) and the runtime wiring in PyramidSearch
(only fires FTS-only + empty-pipeline + anchored-non-temporal; never disturbs a
healthy keyword result; no-op when an embedder/reranker is present). Deterministic
— no LLM, no network, no embedder.
"""
from __future__ import annotations

import types

import pytest

from radiomind.core.config import Config
from radiomind.core.mind import RadioMind
from radiomind.core.types import MemoryEntry, MemoryLevel, SearchResult
from radiomind.storage import facet_rerank as fr


# ----------------------------- pure: the gate -----------------------------

@pytest.mark.parametrize("q,expect", [
    ("How much did I save on the Jimmy Choo heels?", True),       # entity anchor
    ("Where did I redeem a $5 coupon on coffee creamer?", True),  # amount anchor
    ("How much cashback did I earn at SaveMart last Thursday?", True),  # 'last' ok
])
def test_gate_enables_on_anchor(q, expect):
    ok, _ = fr.should_rerank(q)
    assert ok is expect


@pytest.mark.parametrize("q,reason", [
    ("What is the order of the concerts, starting from the earliest?", "temporal_or_ordering"),
    ("When did I start my job?", "temporal_or_ordering"),
    ("How many months have passed since the charity events?", "temporal_or_ordering"),
    ("List the books I read this year", "temporal_or_ordering"),
    ("What degree did I graduate with?", "no_facet_anchor"),
    ("我在哪里买的鞋子", "cjk_query"),
])
def test_gate_skips(q, reason):
    ok, r = fr.should_rerank(q)
    assert ok is False and r == reason


# --------------------------- pure: the scoring ---------------------------

def _sr(content, score, role="user", turn_id="t", date=""):
    e = MemoryEntry(content=content, domain="d", level=MemoryLevel.FACT)
    e.metadata = {"turn_id": turn_id, "role": role, "session_date": date}
    return SearchResult(entry=e, score=score, method="fts_or")


def test_rerank_promotes_anchored_low_fts_candidate():
    # The anchored gold turn has a LOW fts score but high entity overlap; two
    # distractors have higher fts but no facet overlap. Facets must promote gold.
    pool = [
        _sr("[user] random chatter about the weather today", 9.0, turn_id="d1"),
        _sr("[user] more unrelated small talk here", 8.0, turn_id="d2"),
        _sr("[user] I bought the Jimmy Choo heels, paid $180", 1.0, turn_id="gold"),
    ]
    out, dbg = fr.rerank("How much did I save on the Jimmy Choo heels?", "", pool, 30)
    assert dbg["used"] is True
    assert out[0].entry.metadata["turn_id"] == "gold"
    assert out[0].method == "fts_facet"


def test_rerank_noop_when_gated_off():
    pool = [_sr("[user] anything", 1.0, turn_id="x")]
    out, dbg = fr.rerank("When did I travel?", "", pool, 30)
    assert dbg["used"] is False and dbg["reason"] == "temporal_or_ordering"
    assert out is pool  # unchanged object


def test_rerank_empty_pool():
    out, dbg = fr.rerank("Where is the Jimmy Choo store?", "", [], 30)
    assert dbg["used"] is False and out == []


# --------------------------- runtime wiring ---------------------------

@pytest.fixture
def mind(tmp_path):
    cfg = Config()
    cfg.set("general.home", str(tmp_path / ".radiomind"))
    m = RadioMind(config=cfg)
    m.initialize()
    yield m
    m.shutdown()


def _ingest(m, turns):
    rows = [{"role": r, "content": f"[{r}] {c}",
             "metadata": {"turn_id": tid, "role": r, "session_date": "2023-05-01"}}
            for (r, c, tid) in turns]
    m.ingest_turns_raw(rows, domain="d", run_aggregation=False, run_refinement=False)


def test_recovers_when_fts_and_empty(mind):
    # bb7c3b45 shape: no single memory carries every query term, so AND-FTS
    # returns nothing; OR + entity facet recovers the anchored gold turn.
    _ingest(mind, [
        ("user", "I love talking about the weather and my cat", "d1"),
        ("user", "My favourite colour is blue and I enjoy hiking", "d2"),
        ("user", "I finally bought the Jimmy Choo heels at the boutique", "gold"),
        ("assistant", "Great choice on those shoes!", "d3"),
    ])
    res = mind.search("How much did I save on the Jimmy Choo heels?",
                      domain="d", max_results=30, fuse_habits=False)
    dbg = mind._pyramid._last_facet_debug
    assert dbg and dbg["used"] is True and dbg["reason"] == "anchored"
    tids = [(r.entry.metadata or {}).get("turn_id") for r in res]
    assert "gold" in tids
    assert any(r.method == "fts_facet" for r in res)


def test_does_not_disturb_healthy_fts(mind):
    # When AND-FTS already returns candidates, the rerank must NOT run.
    _ingest(mind, [
        ("user", "I redeemed a coupon at SaveMart for groceries", "gold"),
        ("user", "unrelated note about my commute", "d1"),
    ])
    res = mind.search("coupon SaveMart", domain="d", max_results=30, fuse_habits=False)
    dbg = mind._pyramid._last_facet_debug
    assert dbg is not None and dbg["used"] is False and dbg["reason"] == "fts_nonempty"
    assert res and res[0].method != "fts_facet"


def test_temporal_query_not_reranked(mind):
    _ingest(mind, [("user", "I went to the Jimmy Choo store in spring", "g")])
    mind.search("When did I visit the Jimmy Choo store?",
                domain="d", max_results=30, fuse_habits=False)
    dbg = mind._pyramid._last_facet_debug
    assert dbg["used"] is False and dbg["reason"] == "temporal_or_ordering"


def test_no_rerank_when_embedder_present(mind):
    # Guard: with an embedder attached, the FTS-only facet path must not run.
    called = {"n": 0}
    orig = mind._pyramid._maybe_facet_rerank
    def spy(q, fused, mr):
        called["n"] += 1
        return orig(q, fused, mr)
    mind._pyramid._maybe_facet_rerank = spy
    mind._pyramid._embedder = types.SimpleNamespace(is_available=False)  # truthy, not None
    _ingest(mind, [("user", "I bought the Jimmy Choo heels", "g")])
    mind.search("How much did I save on the Jimmy Choo heels?",
                domain="d", max_results=30, fuse_habits=False)
    assert called["n"] == 0
