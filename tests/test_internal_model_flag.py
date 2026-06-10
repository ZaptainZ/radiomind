"""v4pro-split: --internal-model/--internal-profile let the ingest pipeline
stay on a fast model while the answer call uses a heavyweight one.
Default (None) must resolve to the answer model — behavior unchanged.

Deterministic — no LLM, no run.
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
    spec = importlib.util.spec_from_file_location("run_lme_mem0_split", _RUN)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


R = _load()


def test_run_signature_defaults_none():
    sig = inspect.signature(R.run)
    assert sig.parameters["internal_model"].default is None
    assert sig.parameters["internal_profile"].default is None


def test_run_resolves_internal_to_answer_when_none():
    src = inspect.getsource(R.run)
    assert "_int_model = internal_model or answer_model" in src
    assert "_int_profile = internal_profile or answer_profile" in src
    # the internal pipeline callable uses the resolved pair, not answer_*
    assert "model=_int_model" in src
    assert "profile=_int_profile" in src


def test_report_records_internal_model():
    src = inspect.getsource(R.run)
    assert '"internal_model": _int_model' in src
    assert '"internal_profile": _int_profile' in src


def test_main_exposes_flags_and_passes_through():
    src = inspect.getsource(R.main)
    assert "--internal-model" in src
    assert "--internal-profile" in src
    assert "internal_model=args.internal_model" in src
    assert "internal_profile=args.internal_profile" in src
