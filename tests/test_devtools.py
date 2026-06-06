"""Deterministic tests for bench/end_to_end/devtools.py (PX-1b).

Covers ONLY the dispatch / argv-construction surface — the pure `plan()` and
the `run()` forwarding wiring. NO real gate runs: `plan()` imports nothing
heavy, and the one `run()` test mocks the target module's `main()` so no
benchmark / ingest / LLM is ever triggered.

Key guards:
  - target-pack WITHOUT --report must fail (SystemExit) → devtools can never
    fall into target_pack's heavy real-e2e run path.
  - each verb maps to the right existing bench module + argv.
  - run() forwards the planned argv to the module's main() and restores sys.argv.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_DT = (Path(__file__).resolve().parents[1]
       / "bench" / "end_to_end" / "devtools.py")


def _load():
    spec = importlib.util.spec_from_file_location("devtools", _DT)
    m = importlib.util.module_from_spec(spec)
    # Register before exec so the dataclass can resolve its (stringized,
    # PEP 563) annotations via sys.modules during class creation.
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


DT = _load()


# ---------------- plan(): regression-pack ----------------

def test_regression_pack_maps_to_module():
    d = DT.plan(["regression-pack"])
    assert d.command == "regression-pack"
    assert d.module == "regression_pack"
    assert d.argv == []


def test_regression_pack_forwards_integration_flag():
    d = DT.plan(["regression-pack", "--integration"])
    assert d.module == "regression_pack"
    assert d.argv == ["--integration"]


# ---------------- plan(): target-pack ----------------

def test_target_pack_requires_report_else_systemexit():
    # The core safety rail: a bare `target-pack` must NOT be plannable, so
    # devtools can never trigger target_pack's heavy real-e2e run.
    with pytest.raises(SystemExit):
        DT.plan(["target-pack"])


def test_target_pack_report_maps_to_report_mode():
    d = DT.plan(["target-pack", "--report", "path/to/artifact.json"])
    assert d.command == "target-pack"
    assert d.module == "target_pack"
    assert d.argv == ["--report", "path/to/artifact.json"]


def test_target_pack_never_constructs_a_run_argv():
    # No matter what, the forwarded argv for target-pack must carry --report
    # (report mode) and must not be a bare run invocation.
    d = DT.plan(["target-pack", "--report", "x.json"])
    assert "--report" in d.argv
    # report mode is the only path; no answer/judge model args leak through.
    for run_only in ("--answer-model", "--judge-model", "--out"):
        assert run_only not in d.argv


# ---------------- plan(): diagnose ----------------

def test_diagnose_requires_qid():
    with pytest.raises(SystemExit):
        DT.plan(["diagnose"])


def test_diagnose_minimal_argv():
    d = DT.plan(["diagnose", "--qid", "c18a7dc8"])
    assert d.command == "diagnose"
    assert d.module == "diagnose_qid"
    assert d.argv == ["--qid", "c18a7dc8"]


def test_diagnose_full_argv_construction():
    d = DT.plan([
        "diagnose", "--qid", "c18a7dc8",
        "--e2e-result", "run.json",
        "--sandbox", "/tmp/rm-x",
        "--keep-sandbox",
        "--out", "out.json",
    ])
    assert d.module == "diagnose_qid"
    assert d.argv == [
        "--qid", "c18a7dc8",
        "--e2e-result", "run.json",
        "--sandbox", "/tmp/rm-x",
        "--keep-sandbox",
        "--out", "out.json",
    ]


# ---------------- plan(): report (PX-1c) ----------------

def test_report_requires_diagnose_json_and_out():
    with pytest.raises(SystemExit):
        DT.plan(["report"])
    with pytest.raises(SystemExit):
        DT.plan(["report", "--diagnose-json", "d.json"])  # missing --out


def test_report_maps_to_diagnosis_report_module():
    d = DT.plan(["report", "--diagnose-json", "diagnose-c18a7dc8.json",
                 "--out", "report-dir"])
    assert d.command == "report"
    assert d.module == "diagnosis_report"
    assert d.argv == ["--diagnose-json", "diagnose-c18a7dc8.json",
                      "--out", "report-dir"]


def test_report_batch_maps_to_diagnosis_report():
    d = DT.plan(["report", "--target-pack-artifact", "target-pack.json",
                 "--out", "rep"])
    assert d.command == "report"
    assert d.module == "diagnosis_report"
    assert d.argv == ["--target-pack-artifact", "target-pack.json",
                      "--out", "rep"]


def test_report_batch_forwards_diagnose_dir():
    d = DT.plan(["report", "--target-pack-artifact", "tp.json",
                 "--out", "rep", "--diagnose-dir", "bench/end_to_end"])
    assert d.argv == ["--target-pack-artifact", "tp.json", "--out", "rep",
                      "--diagnose-dir", "bench/end_to_end"]


def test_report_modes_mutually_exclusive():
    with pytest.raises(SystemExit):
        DT.plan(["report", "--diagnose-json", "d.json",
                 "--target-pack-artifact", "a.json", "--out", "rep"])


# ---------------- plan(): stability-report (VR-3b) ----------------

def test_stability_report_maps():
    d = DT.plan(["stability-report", "--artifacts", "a.json", "b.json",
                 "--out", "rep"])
    assert d.command == "stability-report"
    assert d.module == "stability_report"
    assert d.argv == ["--artifacts", "a.json", "b.json", "--out", "rep"]


def test_stability_report_forwards_flags():
    d = DT.plan(["stability-report", "--artifacts", "a.json", "b.json",
                 "--out", "rep", "--same-arch", "--current", "a.json"])
    assert "--same-arch" in d.argv
    assert d.argv[-2:] == ["--current", "a.json"]


def test_stability_report_requires_artifacts_and_out():
    with pytest.raises(SystemExit):
        DT.plan(["stability-report", "--out", "rep"])


def test_unknown_command_systemexit():
    with pytest.raises(SystemExit):
        DT.plan(["not-a-command"])


def test_no_command_systemexit():
    with pytest.raises(SystemExit):
        DT.plan([])


# ---------------- run(): forwarding wiring (mocked, no real gate) ----------------

def test_run_forwards_argv_and_restores(monkeypatch):
    """run() must hand the planned argv to the module's main() (as sys.argv[1:])
    and restore the caller's sys.argv afterwards. The module is mocked so NO
    real pack/ingest/LLM runs."""
    captured = {}

    class _FakeModule:
        @staticmethod
        def main():
            captured["argv"] = list(sys.argv)
            return 0

    def _fake_import(name):
        captured["module"] = name
        return _FakeModule

    import importlib
    monkeypatch.setattr(importlib, "import_module", _fake_import)

    sentinel = ["sentinel-preserved"]
    monkeypatch.setattr(sys, "argv", sentinel)

    rc = DT.run(["regression-pack"])
    assert rc == 0
    assert captured["module"] == "regression_pack"
    # main() saw the forwarded argv, prog name first
    assert captured["argv"][0] == "regression_pack.py"
    assert captured["argv"][1:] == []
    # caller's sys.argv restored
    assert sys.argv is sentinel


def test_run_propagates_nonzero_exit(monkeypatch):
    class _FakeModule:
        @staticmethod
        def main():
            return 1

    import importlib
    monkeypatch.setattr(importlib, "import_module", lambda name: _FakeModule)
    rc = DT.run(["target-pack", "--report", "x.json"])
    assert rc == 1
