"""Origin-3b: deterministic guards for the bench-only --dream-after-ingest
flag. NO real ingest / LLM / dream run. Verifies: default off, the
flag-combination validator, run() carries dream_after_ingest (default False),
the dream call is gated on the flag AND not-answer-only, telemetry recorded.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

_RUN = (Path(__file__).resolve().parents[1]
        / "bench" / "end_to_end" / "run_longmemeval_mem0.py")


def _load():
    sys.path.insert(0, str(_RUN.parent))
    spec = importlib.util.spec_from_file_location("run_lme_mem0_o3b", _RUN)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


R = _load()


# ---------------- _validate_dream_flag ----------------

def test_default_no_flags_ok():
    assert R._validate_dream_flag(False, False) is None


def test_dream_with_answer_only_errors():
    err = R._validate_dream_flag(True, True)
    assert err and "--answer-only" in err


def test_dream_alone_ok():
    assert R._validate_dream_flag(True, False) is None


def test_answer_only_alone_ok():
    assert R._validate_dream_flag(False, True) is None


# ---------------- run() signature: default unchanged ----------------

def test_run_has_dream_default_false():
    sig = inspect.signature(R.run)
    assert "dream_after_ingest" in sig.parameters
    assert sig.parameters["dream_after_ingest"].default is False


# ---------------- source guards: gating + telemetry present ----------------

def test_run_gates_dream_on_flag_and_not_answer_only():
    src = inspect.getsource(R.run)
    assert "if dream_after_ingest and not answer_only:" in src
    assert "mind.trigger_dream()" in src
    # failure recorded, never fatal
    assert "dream_stats = {\"error\":" in src.replace("'", '"')


def test_run_records_dream_telemetry():
    src = inspect.getsource(R.run)
    assert "record[\"dream_stats\"] = dream_stats" in src.replace("'", '"')


def test_main_exposes_flag_and_validates():
    src = inspect.getsource(R.main)
    assert "--dream-after-ingest" in src
    assert "_validate_dream_flag(" in src
    assert "dream_after_ingest=args.dream_after_ingest" in src
