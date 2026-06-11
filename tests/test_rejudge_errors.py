"""Rejudge tool-debt fix: selection must use the judge_failed boolean, not
verdict_tail substring matching (tail keeps only the LAST 120 chars, which
truncated the '[judge error' prefix on 3 SSL errors in the 2026-06-06 run2
and made the substring check miss them).

Deterministic — no network, no LLM.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_R = (Path(__file__).resolve().parents[1]
      / "bench" / "end_to_end" / "rejudge_errors.py")


def _load():
    spec = importlib.util.spec_from_file_location("rejudge_errors_t", _R)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


R = _load()


# ---------------- needs_rejudge: boolean is authoritative ----------------

def test_judge_failed_true_with_truncated_tail():
    # the VR-4a miss: tail truncation cut the '[judge error' prefix
    rec = {"judge_failed": True,
           "verdict_tail": "…SSL: UNEXPECTED_EOF_WHILE_READING] occurred"}
    assert R.needs_rejudge(rec)


def test_judge_failed_true_with_empty_tail():
    assert R.needs_rejudge({"judge_failed": True, "verdict_tail": ""})


def test_judge_failed_false_is_authoritative():
    # field present and False wins even if the tail looks error-ish
    rec = {"judge_failed": False,
           "verdict_tail": "[judge error mentioned in passing] … yes"}
    assert not R.needs_rejudge(rec)


def test_clean_pass_record_not_selected():
    rec = {"judge_failed": False, "verdict_tail": "Brief reasoning. yes"}
    assert not R.needs_rejudge(rec)


# ---------------- legacy artifacts: substring fallback ----------------

def test_legacy_substring_match_selected():
    assert R.needs_rejudge({"verdict_tail": "[judge error: 403 Forbidden]"})
    assert R.needs_rejudge({"verdict_tail": "HTTP Error 403"})


def test_legacy_clean_not_selected():
    assert not R.needs_rejudge({"verdict_tail": "reasoning … yes"})
    assert not R.needs_rejudge({})


# ---------------- parse_verdict sanity (unchanged behavior) ----------------

def test_parse_verdict_yes_no():
    assert R.parse_verdict("The response matches the gold. yes")
    assert not R.parse_verdict("The response misses the date. no")


# ---------------- by_type recompute (2026-06-11 debt) ----------------

def test_recompute_by_type_from_per_query():
    data = {"per_query": [
        {"qtype": "a", "correct": True}, {"qtype": "a", "correct": False},
        {"qtype": "b", "correct": True},
    ], "by_type": {"a": {"n": 99, "accuracy": 0.0}}}  # stale
    R.recompute_by_type(data)
    assert data["by_type"]["a"] == {"n": 2, "correct": 1, "accuracy": 0.5}
    assert data["by_type"]["b"]["accuracy"] == 1.0


def test_recompute_by_type_empty_no_clobber():
    data = {"per_query": [], "by_type": {"keep": {"n": 1}}}
    R.recompute_by_type(data)
    assert data["by_type"] == {"keep": {"n": 1}}  # nothing to rebuild from
