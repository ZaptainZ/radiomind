"""Deterministic tests for stability_report.py (VR-3b). Pure parser; no runs."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SR = (Path(__file__).resolve().parents[1]
       / "bench" / "end_to_end" / "stability_report.py")


def _load():
    spec = importlib.util.spec_from_file_location("stability_report", _SR)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


SR = _load()


def _art(order, correct, qtypes=None, acc=None, am="deepseek-v3.2", jm="gpt-4o"):
    """Build a fake runner artifact. order=list of qids; correct=dict qid->bool."""
    pq = [{"question_id": q, "correct": bool(correct[q]),
           "qtype": (qtypes or {}).get(q, "t")} for q in order]
    return {"per_query": pq, "overall_accuracy": acc,
            "answer_model": am, "judge_model": jm}


ORDER = ["q1", "q2", "q3", "q4"]


def _runs_3():
    # q1 always pass, q2 always fail, q3 2/3 pass, q4 1/3 pass
    r1 = _art(ORDER, {"q1": 1, "q2": 0, "q3": 1, "q4": 0})
    r2 = _art(ORDER, {"q1": 1, "q2": 0, "q3": 1, "q4": 1})
    r3 = _art(ORDER, {"q1": 1, "q2": 0, "q3": 0, "q4": 0})
    return [("r1.json", r1), ("r2.json", r2), ("r3.json", r3)]


# ---------------- validation ----------------

def test_needs_two_runs():
    with pytest.raises(SR.StabilityInputError):
        SR.build_stability_report([("a", _art(ORDER, {q: 1 for q in ORDER}))])


def test_same_set_different_order_fails():
    a = _art(ORDER, {q: 1 for q in ORDER})
    b = _art(["q2", "q1", "q3", "q4"], {q: 1 for q in ORDER})
    with pytest.raises(SR.StabilityInputError) as e:
        SR.build_stability_report([("a", a), ("b", b)])
    assert "ORDER differs" in str(e.value)


def test_different_set_fails():
    a = _art(ORDER, {q: 1 for q in ORDER})
    b = _art(["q1", "q2", "q3", "qX"], {"q1": 1, "q2": 1, "q3": 1, "qX": 1})
    with pytest.raises(SR.StabilityInputError) as e:
        SR.build_stability_report([("a", a), ("b", b)])
    assert "SET differs" in str(e.value)


def test_length_mismatch_fails():
    a = _art(ORDER, {q: 1 for q in ORDER})
    b = _art(ORDER[:3], {"q1": 1, "q2": 1, "q3": 1})
    with pytest.raises(SR.StabilityInputError):
        SR.build_stability_report([("a", a), ("b", b)])


# ---------------- aggregate stats ----------------

def test_mean_std_min_max():
    rep = SR.build_stability_report(_runs_3())
    agg = rep["aggregate"]
    # scores: r1=0.5, r2=0.75, r3=0.25
    assert agg["n_runs"] == 3
    assert agg["min"] == 0.25 and agg["max"] == 0.75
    assert agg["mean"] == 0.5
    assert agg["std"] > 0
    assert agg["interpretation"] == "cross-version-envelope"


def test_same_arch_relabels_only():
    rep = SR.build_stability_report(_runs_3(), same_arch=True)
    assert rep["aggregate"]["interpretation"] == "same-arch-stability"


# ---------------- per-qid + unstable ----------------

def test_per_qid_pass_rate_and_mode():
    rep = SR.build_stability_report(_runs_3())
    by = {r["qid"]: r for r in rep["per_qid"]}
    assert by["q1"]["pass_rate"] == 1.0 and by["q1"]["stable"] and by["q1"]["mode_verdict"] == "P"
    assert by["q2"]["pass_rate"] == 0.0 and by["q2"]["stable"] and by["q2"]["mode_verdict"] == "F"
    assert by["q3"]["pass_rate"] == round(2/3, 4) and not by["q3"]["stable"]
    assert by["q3"]["mode_verdict"] == "P"
    assert by["q4"]["pass_rate"] == round(1/3, 4) and by["q4"]["mode_verdict"] == "F"


def test_unstable_sorted_by_closeness_to_half():
    rep = SR.build_stability_report(_runs_3())
    un = [r["qid"] for r in rep["unstable_qids"]]
    # q3 (0.667) and q4 (0.333) are both 0.167 from 0.5 → both unstable
    assert set(un) == {"q3", "q4"}
    assert rep["family_summary"] == {"stable_pass": 1, "stable_fail": 1, "unstable": 2}


def test_tie_mode_when_even_split():
    a = _art(["q1"], {"q1": 1})
    b = _art(["q1"], {"q1": 0})
    rep = SR.build_stability_report([("a", a), ("b", b)])
    assert rep["per_qid"][0]["mode_verdict"] == "TIE"
    assert rep["per_qid"][0]["pass_rate"] == 0.5


# ---------------- placement ----------------

def test_placement_flags_max():
    runs = _runs_3()
    rep = SR.build_stability_report(runs, current="r2.json")  # r2=0.75=max
    p = rep["placement"]
    assert p["is_max"] is True and p["is_min"] is False
    assert p["delta_vs_max"] == 0.0


# ---------------- summary md caveat ----------------

def test_summary_md_envelope_caveat():
    md = SR.render_summary_md(SR.build_stability_report(_runs_3()))
    assert "cross-version envelope" in md
    assert "NOT a pure" in md
    assert "Unstable qids" in md


def test_summary_md_same_arch_caveat():
    md = SR.render_summary_md(SR.build_stability_report(_runs_3(), same_arch=True))
    assert "same-arch stability" in md


def test_write_stability_two_files(tmp_path):
    paths = SR.write_stability(SR.build_stability_report(_runs_3()), tmp_path / "o")
    assert paths["stability_json"].exists() and paths["summary_md"].exists()
