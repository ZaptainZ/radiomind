"""VR-2b — deterministic guards for the bench-only answer-only mode.

NO real ingest / LLM / run. Verifies: the flag-combination validator, the CLI
exposes both flags, run() carries answer_only (default False), and the
wipe/ingest are gated on it so the DEFAULT path is unchanged.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

_RUN = (Path(__file__).resolve().parents[1]
        / "bench" / "end_to_end" / "run_longmemeval_mem0.py")


def _load():
    spec = importlib.util.spec_from_file_location("run_longmemeval_mem0", _RUN)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


R = _load()


# ---------------- _validate_answer_only ----------------

def test_default_no_flags_ok():
    assert R._validate_answer_only(False, False, "") is None


def test_reuse_without_answer_only_errors():
    err = R._validate_answer_only(False, True, "")
    assert err and "no effect" in err


def test_answer_only_without_reuse_errors():
    err = R._validate_answer_only(True, False, "9ee3ecd6")
    assert err and "reuse-existing-sandbox" in err


def test_answer_only_without_qids_errors():
    err = R._validate_answer_only(True, True, "")
    assert err and "--qids" in err
    assert R._validate_answer_only(True, True, "   ") is not None  # whitespace


def test_answer_only_full_combo_ok():
    assert R._validate_answer_only(True, True, "9ee3ecd6,1c0ddc50") is None


# ---------------- run() signature: default unchanged ----------------

def test_run_has_answer_only_default_false():
    sig = inspect.signature(R.run)
    assert "answer_only" in sig.parameters
    assert sig.parameters["answer_only"].default is False


# ---------------- source guards: gating present ----------------

def test_run_gates_wipe_and_ingest_on_answer_only():
    src = inspect.getsource(R.run)
    # wipe is skipped in answer-only mode
    assert "if not answer_only and (sandbox / \"data\").exists():" in src
    # ingest is skipped in answer-only mode
    assert "if answer_only:" in src
    assert "stats = {\"ingested\": 0}" in src
    # empty-retrieval hard fail
    assert "answer_only and not results" in src


def test_main_exposes_both_flags_and_validates():
    src = inspect.getsource(R.main)
    assert "--answer-only" in src
    assert "--reuse-existing-sandbox" in src
    assert "_validate_answer_only(" in src
    assert "answer_only=args.answer_only" in src
