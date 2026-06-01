"""Deterministic tests for target_pack.summarize — the harness logic only
(no runner, no LLM). Guards: required gates the exit; observe_only never
reds; missing required = fail; missing observe = noted, not fatal.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_TP = (Path(__file__).resolve().parents[1]
       / "bench" / "end_to_end" / "target_pack.py")


def _load():
    spec = importlib.util.spec_from_file_location("target_pack", _TP)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


TP = _load()


def _pq(**qid_correct):
    return [{"question_id": q, "correct": c} for q, c in qid_correct.items()]


def test_all_required_pass_and_observe_fail_still_green():
    # every required correct; observe-only failing must NOT red the gate
    pq = {q: True for q, m in TP.MANIFEST.items() if m["mode"] == "required"}
    pq.update({q: False for q, m in TP.MANIFEST.items()
               if m["mode"] == "observe_only"})
    s = TP.summarize(_pq(**pq), TP.MANIFEST)
    assert s["required_all_pass"] is True
    assert s["required_pass"] == s["required_total"]
    assert s["observe_pass"] < s["observe_total"]   # observe failed, gate green


def test_a_failing_required_reds_the_gate():
    pq = {q: True for q, m in TP.MANIFEST.items() if m["mode"] == "required"}
    a_required = next(q for q, m in TP.MANIFEST.items() if m["mode"] == "required")
    pq[a_required] = False
    s = TP.summarize(_pq(**pq), TP.MANIFEST)
    assert s["required_all_pass"] is False


def test_missing_required_counts_as_fail():
    # omit one required qid entirely from per_query
    a_required = next(q for q, m in TP.MANIFEST.items() if m["mode"] == "required")
    pq = {q: True for q, m in TP.MANIFEST.items()
          if m["mode"] == "required" and q != a_required}
    s = TP.summarize(_pq(**pq), TP.MANIFEST)
    assert s["required_all_pass"] is False
    row = next(r for r in s["rows"] if r["qid"] == a_required)
    assert row["present"] is False and row["ok"] is False


def test_manifest_shape():
    modes = {m["mode"] for m in TP.MANIFEST.values()}
    assert modes <= {"required", "observe_only"}
    assert any(m["mode"] == "required" for m in TP.MANIFEST.values())
    assert any(m["mode"] == "observe_only" for m in TP.MANIFEST.values())
    # the agreed observe-only / parked lines
    assert TP.MANIFEST["gpt4_7abb270c"]["mode"] == "observe_only"
    assert TP.MANIFEST["b46e15ed"]["mode"] == "observe_only"
