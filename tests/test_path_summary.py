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


# --- DX-2b: e2e final-answer overlay -------------------------------------

def _closure_ready_rec():
    return _rec(closure_view={
        "committers": {"cashback": {
            "proof_available": True,
            "would_commit_on_canonical_abstain": True,
            "would_overwrite_concrete_answer": False,
            "proof": {"value": 0.75},
        }},
        "suppressors": {},
    })


def test_e2e_correct_marks_pass():
    s = DQ.build_path_summary(
        _closure_ready_rec(),
        e2e={"question_id": "q", "answer": "$0.75", "correct": True,
             "judge_failed": False})
    assert s["diagnosis"]["layer"] == "pass"
    assert s["final_answer"]["correct"] is True


def test_e2e_answer_error_attributes_to_answer_path():
    s = DQ.build_path_summary(
        _closure_ready_rec(),
        e2e={"question_id": "q",
             "answer": "[answer error: <urlopen error [Errno 8]>]",
             "correct": False, "judge_failed": False})
    assert s["diagnosis"]["layer"] == "answer_or_judge_path"
    assert s["final_answer"]["answer_error"] is True


def test_e2e_judge_failed_attributes_to_judge_path():
    s = DQ.build_path_summary(
        _closure_ready_rec(),
        e2e={"question_id": "q", "answer": "$0.75", "correct": False,
             "judge_failed": True})
    assert s["diagnosis"]["layer"] == "answer_or_judge_path"
    assert "judge" in s["diagnosis"]["reason"]


def test_e2e_wrong_with_ready_closure_is_trust_gap():
    # deterministic layer was closure_ready, answer wrong, no infra error
    # => answer-LLM ignored the proof (trust-gap), not a logic gap
    s = DQ.build_path_summary(
        _closure_ready_rec(),
        e2e={"question_id": "q", "answer": "I'm not sure.", "correct": False,
             "judge_failed": False,
             "helper_hints": {"answer_pure_abstain": True}})
    assert s["diagnosis"]["layer"] == "answer_or_judge_path"
    assert s["final_answer"]["pure_abstain"] is True


def test_e2e_wrong_without_closure_keeps_deterministic_layer():
    # retrieval_gap stays retrieval_gap even with a wrong e2e answer
    rec = _rec(retrieve_window={"gold_hits_in_top_200": 0,
                                "gold_hits_in_top_30": 0})
    s = DQ.build_path_summary(
        rec, e2e={"question_id": "q", "answer": "nope", "correct": False,
                  "judge_failed": False})
    assert s["diagnosis"]["layer"] == "retrieval_gap"


def test_no_e2e_means_no_final_answer_field():
    s = DQ.build_path_summary(_closure_ready_rec())
    assert "final_answer" not in s


def test_load_e2e_record_matches_question_id(tmp_path):
    import json
    p = tmp_path / "result.json"
    p.write_text(json.dumps({"per_query": [
        {"question_id": "other", "answer": "x"},
        {"question_id": "q", "answer": "$0.75", "correct": True},
    ]}))
    rec = DQ._load_e2e_record(p, "q")
    assert rec is not None and rec["answer"] == "$0.75"
    assert DQ._load_e2e_record(p, "missing") is None


def test_print_does_not_crash_with_final_answer():
    s = DQ.build_path_summary(
        _closure_ready_rec(),
        e2e={"question_id": "q",
             "answer": "[answer error: x]", "correct": False,
             "judge_failed": False})
    DQ._print_path_summary(s)
