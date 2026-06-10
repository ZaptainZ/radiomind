"""Origin-1b-hygiene: deterministic guards for the three hygiene fixes.

1. DELTA example de-benchmarked — the answer prompt must not contain the
   9ee3ecd6-derived 200/300/100 example numbers (generic 50/120/70 instead).
2. Truncated-stub detector + single regeneration with telemetry.
3. per_query prompt_sections observability record (cardinal/atomic).

NO real ingest / LLM / network.
"""
from __future__ import annotations

import importlib.util
import sys
import urllib.error
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[1] / "bench" / "end_to_end"


def _load(path: Path, name: str):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


R = _load(_BENCH / "run_longmemeval_mem0.py", "run_lme_mem0_o1b")


# ---------------- 1. DELTA example de-benchmarked ----------------

def test_delta_example_no_benchmark_numbers():
    P = _load(_BENCH / "mem0_protocol" / "longmemeval_prompts.py",
              "lme_prompts_o1b")
    text = "\n".join(
        v for v in vars(P).values() if isinstance(v, str))
    # the 9ee3ecd6-derived example trio must be gone
    assert "I have 200 points now" not in text
    assert "total of 300 to redeem" not in text
    assert "NOT the target (300)" not in text
    # the generic replacement is present and arithmetically consistent
    assert "I have 50 points now" in text
    assert "total of 120 to redeem" in text
    assert "(= 70)" in text
    assert "NOT the target (120)" in text


def test_delta_rule_itself_still_present():
    P = sys.modules["lme_prompts_o1b"]
    text = "\n".join(v for v in vars(P).values() if isinstance(v, str))
    assert "DELTA vs ABSOLUTE" in text  # hygiene fix, not rule removal


# ---------------- 2. truncated-stub detector ----------------

def test_stub_detector_catches_observed_stub_and_empty():
    assert R._is_truncated_stub("You currently own")
    assert R._is_truncated_stub("")
    assert R._is_truncated_stub("   ")
    assert R._is_truncated_stub("The total is the")


def test_stub_detector_never_flags_legal_short_answers():
    for legal in ("$300", "7", "8 miles", "four", "100",
                  "The information provided is not enough.",
                  "The information provided is not enough",
                  "You saved $300.",
                  "October 25, 2022",
                  "[answer error: dns down]"):
        assert not R._is_truncated_stub(legal), legal


def test_stub_triggers_single_regen_with_telemetry(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_llm_call(prompt, cfg, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return "You currently own"
        return "You currently own 4 musical instruments."

    monkeypatch.setattr(R, "llm_call", fake_llm_call)
    out, reason = R._answer_with_retry("p", None, model="m", profile="pf")
    assert calls["n"] == 2
    assert out == "You currently own 4 musical instruments."
    assert reason == "truncated_stub"


def test_double_stub_returns_longer_no_third_attempt(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_llm_call(prompt, cfg, **kw):
        calls["n"] += 1
        return "You currently own" if calls["n"] == 1 else "I have a"

    monkeypatch.setattr(R, "llm_call", fake_llm_call)
    out, reason = R._answer_with_retry("p", None, model="m", profile="pf")
    assert calls["n"] == 2                      # never a third attempt
    assert out == "You currently own"           # longer of the two stubs
    assert reason == "truncated_stub"


def test_clean_answer_no_regen(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_llm_call(prompt, cfg, **kw):
        calls["n"] += 1
        return "8 miles"

    monkeypatch.setattr(R, "llm_call", fake_llm_call)
    out, reason = R._answer_with_retry("p", None, model="m", profile="pf")
    assert calls["n"] == 1 and out == "8 miles" and reason is None


def test_transient_error_then_stub_then_clean(monkeypatch):
    # exception path and stub path compose: error -> stub -> regen clean
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_llm_call(prompt, cfg, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("blip")
        if calls["n"] == 2:
            return "You currently own"
        return "4"

    monkeypatch.setattr(R, "llm_call", fake_llm_call)
    out, reason = R._answer_with_retry("p", None, model="m", profile="pf")
    assert out == "4" and reason == "truncated_stub"


# ---------------- 3. prompt_sections observability ----------------

def test_prompt_sections_record_fields():
    rec = R._prompt_sections_record("CARDINAL VIEW...\n", "")
    assert rec == {
        "cardinal_present": True, "cardinal_chars": 17,
        "atomic_present": False, "atomic_chars": 0,
    }


def test_prompt_sections_record_both_empty():
    rec = R._prompt_sections_record("", "")
    assert rec["cardinal_present"] is False
    assert rec["atomic_present"] is False
    assert rec["cardinal_chars"] == 0 and rec["atomic_chars"] == 0


def test_prompt_sections_separate_from_helper_hints():
    # contract: prompt sections are NOT folded into helper_hints
    keys = set(R._prompt_sections_record("", ""))
    assert keys == {"cardinal_present", "cardinal_chars",
                    "atomic_present", "atomic_chars"}
