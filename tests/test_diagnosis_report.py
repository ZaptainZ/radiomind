"""Deterministic tests for bench/end_to_end/diagnosis_report.py (PX-1c).

Pure projection only — small JSON fixtures, NO ingest / LLM / diagnose re-run.
Guards:
  - every stabilized diagnosis.layer has fix_family / do_not / next_action.
  - build_diagnosis_report projects path_summary.diagnosis.layer correctly.
  - legacy recs without path_summary degrade to layer='unknown' (no crash).
  - unrecognized layers fall back to 'unknown' guidance + flag.
  - write_report emits exactly diagnosis.json + summary.md and round-trips.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_DR = (Path(__file__).resolve().parents[1]
       / "bench" / "end_to_end" / "diagnosis_report.py")


def _load():
    spec = importlib.util.spec_from_file_location("diagnosis_report", _DR)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


DR = _load()

# Layers the PX-1c scope explicitly must cover.
_REQUIRED_LAYERS = [
    "proof_input_turn_missing",
    "concrete_wrong_bypassed_committer",
    "answer_or_judge_path",
    "helper_refusal",
    "retrieval_gap",
    "closure_ready",
    "pass",
    "unknown",
]


def _rec(layer=None, reason="r", **ps_extra):
    """A minimal diagnose rec with a path_summary block."""
    ps = {"qid": "qX"}
    if layer is not None:
        ps["diagnosis"] = {"layer": layer, "reason": reason}
    ps.update(ps_extra)
    return {"qid": "qX", "path_summary": ps}


# ---------------- guidance table coverage ----------------

def test_every_required_layer_has_full_guidance():
    for layer in _REQUIRED_LAYERS:
        assert layer in DR.LAYER_GUIDANCE, f"missing guidance: {layer}"
        g = DR.LAYER_GUIDANCE[layer]
        for field in ("meaning", "fix_family", "do_not", "next_action"):
            assert g.get(field), f"{layer}.{field} empty"


def test_report_carries_lookup_fields():
    rep = DR.build_diagnosis_report(_rec("proof_input_turn_missing"))
    assert rep["layer"] == "proof_input_turn_missing"
    assert "retrieval" in rep["fix_family"]
    assert "parser" in rep["do_not"]  # do-not: don't edit parser/regex
    assert rep["next_action"]
    assert rep["layer_recognized"] is True


def test_each_required_layer_projects_its_action():
    for layer in _REQUIRED_LAYERS:
        rep = DR.build_diagnosis_report(_rec(layer))
        g = DR.LAYER_GUIDANCE[layer]
        assert rep["fix_family"] == g["fix_family"]
        assert rep["do_not"] == g["do_not"]
        assert rep["next_action"] == g["next_action"]


# ---------------- projection + degradation ----------------

def test_qid_from_top_or_path_summary():
    assert DR.build_diagnosis_report(_rec("pass"))["qid"] == "qX"
    # top-level qid missing → fall back to path_summary.qid
    data = {"path_summary": {"qid": "fromPS", "diagnosis": {"layer": "pass"}}}
    assert DR.build_diagnosis_report(data)["qid"] == "fromPS"


def test_legacy_rec_without_path_summary_degrades_to_unknown():
    rep = DR.build_diagnosis_report({"qid": "old"})  # no path_summary
    assert rep["layer"] == "unknown"
    assert rep["qid"] == "old"
    assert rep["layer_recognized"] is True  # 'unknown' IS a known key
    assert "predates" in rep["reason"] or "incomplete" in rep["reason"]


def test_unrecognized_layer_falls_back_and_flags():
    rep = DR.build_diagnosis_report(_rec("some_future_layer"))
    assert rep["layer"] == "some_future_layer"
    assert rep["layer_recognized"] is False
    # fell back to 'unknown' guidance
    assert rep["fix_family"] == DR.LAYER_GUIDANCE["unknown"]["fix_family"]


def test_context_extracts_verdict_and_flags():
    data = _rec("answer_or_judge_path",
                retrieval={"gold_hits_top_200": 5, "gold_hits_top_30": 5},
                final_answer={"correct": False, "judge_failed": False,
                              "pure_abstain": True, "answer_error": False})
    rep = DR.build_diagnosis_report(data)
    assert rep["context"]["verdict"] == "WRONG"
    assert "pure-abstain" in rep["context"]["flags"]
    assert rep["context"]["retrieval"]["gold_hits_top_200"] == 5


def test_context_verdict_none_when_no_final_answer():
    rep = DR.build_diagnosis_report(_rec("closure_ready"))
    assert rep["context"]["verdict"] is None
    assert rep["context"]["flags"] == []


# ---------------- summary.md rendering ----------------

def test_summary_md_contains_core_fields():
    rep = DR.build_diagnosis_report(_rec("proof_input_turn_missing"),
                                    source="diagnose-qX.json")
    md = DR.render_summary_md(rep)
    assert "# diagnose qX" in md
    assert "proof_input_turn_missing" in md
    assert "Fix family:" in md
    assert "Next action:" in md
    assert "diagnose-qX.json" in md


def test_summary_md_flags_unrecognized_layer():
    md = DR.render_summary_md(
        DR.build_diagnosis_report(_rec("weird_layer")))
    assert "Unrecognized layer" in md


# ---------------- write_report (filesystem, tmp only) ----------------

def test_write_report_emits_two_files(tmp_path):
    rep = DR.build_diagnosis_report(_rec("retrieval_gap"),
                                    source="src.json")
    paths = DR.write_report(rep, tmp_path / "out")
    dj, sm = paths["diagnosis_json"], paths["summary_md"]
    assert dj.name == "diagnosis.json" and dj.exists()
    assert sm.name == "summary.md" and sm.exists()
    # diagnosis.json round-trips and is the same report
    loaded = json.loads(dj.read_text())
    assert loaded["layer"] == "retrieval_gap"
    assert loaded["source"] == "src.json"
    assert "diagnose qX" in sm.read_text()


def test_load_diagnose_json_roundtrip(tmp_path):
    p = tmp_path / "diagnose-qX.json"
    p.write_text(json.dumps(_rec("pass")))
    data = DR.load_diagnose_json(p)
    assert data["path_summary"]["diagnosis"]["layer"] == "pass"


# ---------------- PX-2b: richer context + self-contained summary ----------------

def _full_rec(layer="concrete_wrong_bypassed_committer"):
    """A current-style diagnose rec with question/gold/qtype + final_answer."""
    return {
        "qid": "qX",
        "question": "How much cashback did I earn at TestMart?",
        "gold": "$1.23",
        "qtype": "single-session-user",
        "path_summary": {
            "qid": "qX",
            "diagnosis": {"layer": layer, "reason": "r"},
            "retrieval": {"gold_hits_top_200": 3, "gold_hits_top_30": 1},
            "final_answer": {
                "answer": "You earned $9.99 in cashback.",
                "correct": False, "judge_failed": False,
                "pure_abstain": False, "answer_error": False,
            },
        },
    }


def test_context_carries_question_gold_answer_verdict():
    rep = DR.build_diagnosis_report(_full_rec(), source="diagnose-qX.json")
    c = rep["context"]
    assert "cashback" in c["question"]
    assert c["gold"] == "$1.23"
    assert c["qtype"] == "single-session-user"
    assert "9.99" in c["answer_snippet"]
    assert c["correct"] is False
    assert c["judge_failed"] is False
    assert c["answer_pure_abstain"] is False
    assert c["verdict"] == "WRONG"
    assert c["source_artifact"] == "diagnose-qX.json"


def test_suggested_command_contains_qid_and_placeholder():
    rep = DR.build_diagnosis_report(_full_rec())
    cmd = rep["context"]["suggested_command"]
    assert "devtools diagnose" in cmd
    assert "--qid qX" in cmd
    assert "<e2e-result.json>" in cmd  # placeholder when no artifact given


def test_suggested_command_embeds_real_artifact():
    rep = DR.build_diagnosis_report(_full_rec(),
                                    e2e_artifact="bench/end_to_end/run.json")
    cmd = rep["context"]["suggested_command"]
    assert "--e2e-result bench/end_to_end/run.json" in cmd


def test_manifest_line_explicit_override():
    rep = DR.build_diagnosis_report(_full_rec(), manifest_line="my-line")
    assert rep["context"]["manifest_line"] == "my-line"


def test_manifest_line_autolookup_for_known_qid():
    # c18a7dc8 is in target_pack.MANIFEST as the age-interval-committer line.
    line = DR.lookup_manifest_line("c18a7dc8")
    assert line == "age-interval-committer"
    # and build auto-fills it when manifest_line is None
    data = _full_rec()
    data["qid"] = "c18a7dc8"
    data["path_summary"]["qid"] = "c18a7dc8"
    rep = DR.build_diagnosis_report(data)
    assert rep["context"]["manifest_line"] == "age-interval-committer"


def test_manifest_line_none_for_unknown_qid():
    assert DR.lookup_manifest_line("not-a-real-qid") is None


def test_summary_md_is_self_contained():
    rep = DR.build_diagnosis_report(_full_rec(), source="diagnose-qX.json")
    md = DR.render_summary_md(rep)
    assert "**Question:**" in md and "cashback" in md
    assert "**Gold:** $1.23" in md
    assert "**Answer:**" in md and "9.99" in md
    assert "**Verdict:** WRONG" in md
    assert "## Diagnosis" in md
    assert "## Next command" in md
    assert "--qid qX" in md


def test_summary_md_verdict_na_without_overlay():
    rep = DR.build_diagnosis_report(_rec("closure_ready"))
    md = DR.render_summary_md(rep)
    assert "no e2e overlay" in md


def test_refined_next_actions_point_to_fields():
    cw = DR.LAYER_GUIDANCE["concrete_wrong_bypassed_committer"]["next_action"]
    assert "final_answer.answer" in cw and "closure_view.committers" in cw
    pm = DR.LAYER_GUIDANCE["proof_input_turn_missing"]["next_action"]
    assert "helper_proofs" in pm and "retrieve_top_30_preview" in pm


def test_legacy_rec_still_renders_without_crash():
    # no question/gold/final_answer, no path_summary
    rep = DR.build_diagnosis_report({"qid": "old"}, source="old.json")
    c = rep["context"]
    assert c["question"] is None and c["gold"] is None
    assert c["answer_snippet"] is None and c["verdict"] is None
    md = DR.render_summary_md(rep)  # must not crash
    assert "# diagnose old" in md
    assert "no e2e overlay" in md
    assert "## Next command" in md  # suggested_command always present
