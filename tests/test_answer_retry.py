"""AnswerRetry-1b: the answer-LLM call gets the judge's outer transient-error
retry. Deterministic — monkeypatch llm_call; no network, no model.
"""
from __future__ import annotations

import importlib.util
import sys
import urllib.error
from pathlib import Path

_R = (Path(__file__).resolve().parents[1]
      / "bench" / "end_to_end" / "run_longmemeval_mem0.py")


def _load():
    sys.path.insert(0, str(_R.parent))
    spec = importlib.util.spec_from_file_location("run_lme_mem0", _R)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


R = _load()


def test_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_llm_call(prompt, cfg, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError(
                "<urlopen error [Errno 8] nodename nor servname provided>")
        return "<mem_thinking>noise</mem_thinking>You saved $300."

    monkeypatch.setattr(R, "llm_call", fake_llm_call)
    out, reason = R._answer_with_retry("p", None, model="m", profile="pf")
    assert calls["n"] == 2                 # retried once, then succeeded
    assert "$300" in out
    assert "mem_thinking" not in out       # strip_thinking applied
    assert reason is None                  # transient retry is not stub telemetry


def test_succeeds_first_try_no_retry(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_llm_call(prompt, cfg, **kw):
        calls["n"] += 1
        return "7"

    monkeypatch.setattr(R, "llm_call", fake_llm_call)
    out, reason = R._answer_with_retry("p", None, model="m", profile="pf")
    assert calls["n"] == 1 and out == "7"
    assert reason is None


def test_persistent_error_surfaces_not_swallowed(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_llm_call(prompt, cfg, **kw):
        calls["n"] += 1
        raise urllib.error.URLError("dns down")

    monkeypatch.setattr(R, "llm_call", fake_llm_call)
    out, reason = R._answer_with_retry("p", None, model="m", profile="pf")
    assert calls["n"] == 3                  # exhausted the attempts
    assert out.startswith("[answer error")  # failure surfaced, not a fake answer
    assert reason is None                   # '[answer error: …]' is not a stub
