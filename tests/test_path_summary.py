"""DX-2a: deterministic tests for diagnose_qid.build_path_summary — pure
projection over synthetic `rec` dicts (no ingest, no LLM)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_DQ = (Path(__file__).resolve().parents[1]
       / "bench" / "end_to_end" / "diagnose_qid.py")


def _load():
    spec = importlib.util.spec_from_file_location("diagnose_qid_ps", _DQ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


DQ = _load()


def _rec(**kw):
    base = {
        "qid": "q",
        "retrieve_window": {"gold_hits_in_top_200": 3, "gold_hits_in_top_30": 1},
        "helper_signals": {},
        "helper_proofs": {},
        "structured_skill_section": None,
        "closure_view": {"committers": {}, "suppressors": {}},
    }
    base.update(kw)
    return base


def test_closure_ready_when_committer_would_commit():
    rec = _rec(closure_view={
        "committers": {"cashback": {
            "proof_available": True,
            "would_commit_on_canonical_abstain": True,
            "would_overwrite_concrete_answer": False,
            "proof": {"value": 0.75},
        }},
        "suppressors": {},
    })
    s = DQ.build_path_summary(rec)
    assert s["diagnosis"]["layer"] == "closure_ready"
    assert s["deterministic_layer"]["proofs_available"] == ["cashback"]
    assert s["closure_decision"]["committers"]["cashback"]["would_commit_on_abstain"] is True


def test_closure_ready_when_suppressor_detected():
    rec = _rec(closure_view={
        "committers": {},
        "suppressors": {"role": {"detection": {"x": 1},
                                 "would_suppress_sample_overcommit": True}},
    })
    s = DQ.build_path_summary(rec)
    assert s["diagnosis"]["layer"] == "closure_ready"
    assert s["closure_decision"]["suppressors"]["role"]["detected"] is True


def test_helper_refusal():
    rec = _rec(helper_proofs={
        "savings": {"refusal_reason": "no_trigger_match"},
        "cashback": {"refusal_reason": "no_cashback_rate_in_memories"},
    })
    s = DQ.build_path_summary(rec)
    assert s["diagnosis"]["layer"] == "helper_refusal"
    reasons = {r["helper"]: r["reason"] for r in s["deterministic_layer"]["refused"]}
    assert reasons["savings"] == "no_trigger_match"


def test_proof_ready_when_helper_fired_no_closure():
    rec = _rec(helper_proofs={"savings": {"refusal_reason": None}})
    s = DQ.build_path_summary(rec)
    assert s["diagnosis"]["layer"] == "proof_ready"
    assert "savings" in s["deterministic_layer"]["fired"]


def test_retrieval_gap():
    rec = _rec(retrieve_window={"gold_hits_in_top_200": 0,
                                "gold_hits_in_top_30": 0})
    s = DQ.build_path_summary(rec)
    assert s["diagnosis"]["layer"] == "retrieval_gap"


def test_unknown_when_no_evidence():
    s = DQ.build_path_summary(_rec())
    assert s["diagnosis"]["layer"] == "unknown"
    # skill route always reports list_ordering as not-probed (DX-2a gap)
    assert s["skill_route"]["list_ordering"] == "not_probed"


def test_print_does_not_crash():
    DQ._print_path_summary(DQ.build_path_summary(_rec()))
