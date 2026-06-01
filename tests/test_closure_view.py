"""Regression: pin diagnose_qid's read-only closure_view (Phase2-2b/2c).

Loads bench/end_to_end/diagnose_qid.py and exercises `_probe_closure_view`
on faithful synthetic data — no ingest, no LLM. Covers the cashback + age
committer proof views and the role/TESG suppressor what-ifs. Part of the
local regression pack (bench/end_to_end/regression_pack.py).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_DQ_PATH = (Path(__file__).resolve().parents[1]
            / "bench" / "end_to_end" / "diagnose_qid.py")


def _load_diagnose_qid():
    spec = importlib.util.spec_from_file_location("diagnose_qid_pack", _DQ_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


DQ = _load_diagnose_qid()

CASHBACK_Q = "How much cashback did I earn at SaveMart last Thursday?"
CASHBACK_MEMS = [
    {"memory": "I went grocery shopping at SaveMart last Thursday and "
               "spent $75 on my purchase."},
    {"memory": "By the way, SaveMart has this loyalty program where you "
               "get 1% cashback on all your purchases."},
]

AGE_Q = "How many years older am I than when I graduated from college?"
AGE_MEMS = [
    {"memory": "[user] I completed my Bachelor's at the age of 25."},
    {"memory": "[user] As a 32-year-old Digital Marketing Specialist, "
               "I learn a lot."},
]
AGE_SECTION = ("STRUCTURED SKILL (age_interval, conf=0.90): trust this.\n"
               "Computed answer: 7\n")


def test_cashback_committer_view():
    cv = DQ._probe_closure_view(CASHBACK_Q, CASHBACK_MEMS, None, "d")
    c = cv["committers"]["cashback"]
    assert c["proof_available"] is True
    assert c["proof"]["value"] == 0.75
    assert c["proof"]["rendered"] == "You earned $0.75 in cashback at SaveMart."
    assert c["would_commit_on_canonical_abstain"] is True
    assert c["would_overwrite_concrete_answer"] is False


def test_age_committer_view_dual_source():
    cv = DQ._probe_closure_view(AGE_Q, AGE_MEMS, None, "d", AGE_SECTION)
    a = cv["committers"]["age_interval"]
    assert a["proof_available"] is True
    assert a["proof"]["value"] == 7
    assert a["proof"]["recompute_ok"] is True
    assert a["proof"]["confidence"] == 0.9
    roles = {s["role"] for s in a["proof"]["sources"]}
    assert roles == {"at_age", "current_age"}   # dual provenance
    assert a["would_commit_on_canonical_abstain"] is True
    assert a["would_overwrite_concrete_answer"] is False


def test_committer_absent_when_no_proof():
    # age question → cashback has no proof
    cv = DQ._probe_closure_view(AGE_Q, AGE_MEMS, None, "d", AGE_SECTION)
    assert cv["committers"]["cashback"].get("proof_available") is False
    # cashback question with no temporal section → age has no proof
    cv2 = DQ._probe_closure_view(CASHBACK_Q, CASHBACK_MEMS, None, "d")
    assert cv2["committers"]["age_interval"].get("proof_available") is False


def test_suppressors_present_and_bypass_abstain():
    cv = DQ._probe_closure_view(CASHBACK_Q, CASHBACK_MEMS, None, "d")
    for name in ("role", "temporal_endpoint"):
        s = cv["suppressors"][name]
        assert "error" not in s, s
        # a pure abstain is always passed through by a suppressor
        assert s["would_bypass_canonical_abstain"] is True
        # neither suppressor fires on a cashback question
        assert s["would_suppress_sample_overcommit"] is False
