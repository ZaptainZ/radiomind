"""Tests for V6.3-B: trinity-routed attention.

Backward-compat: analyze_with_trinity(query, llm=None) ≡ analyze(query).
With llm and regex-uncertain queries (wants=lookup), trinity 3-stance
is consulted for upgrade. Retry-consistency requires both calls to
agree; otherwise fall back to regex.
"""
from __future__ import annotations

import json

from radiomind.core.attention import (
    analyze, analyze_with_trinity, AttentionSignature,
    _TRINITY_UPGRADE_TARGETS,
)


class _StubLLM:
    """Returns the same canned trinity JSON every call."""

    def __init__(self, canned: dict | str):
        self._text = canned if isinstance(canned, str) else json.dumps(canned)
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, system=""):
        self.calls += 1
        class _R: pass
        r = _R()
        r.text = self._text
        return r


class _SequenceStubLLM:
    """Returns different canned responses across sequential calls."""

    def __init__(self, seq: list):
        self._seq = [json.dumps(c) if isinstance(c, dict) else c for c in seq]
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, system=""):
        idx = min(self.calls, len(self._seq) - 1)
        self.calls += 1
        class _R: pass
        r = _R()
        r.text = self._seq[idx]
        return r


def _ok_response(wants: str) -> dict:
    return {
        "stances": [
            {"name": "literal-form", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "semantic-intent", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "answer-shape", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
        ],
        "final_answer": f"wants is {wants}",
        "confidence": 0.85,
        "wants": wants,
    }


# === Backward-compat: llm=None must equal analyze() ===


def test_no_llm_returns_regex_result():
    """When llm is None, trinity is never invoked → identical to analyze()."""
    q = "How many years older am I than when I graduated?"
    assert analyze_with_trinity(q, llm=None) == analyze(q)


def test_no_llm_lookup_query_returns_regex_lookup():
    """LoCoMo-style 'Which city is X excited about' → regex says lookup;
    no llm → no upgrade, lookup stays."""
    q = "Which city is John excited to have a game at?"
    sig = analyze_with_trinity(q, llm=None)
    assert sig.wants == "lookup"


# === Short-circuit: high-confidence regex skips trinity ===


def test_high_confidence_regex_count_skips_trinity():
    """Regex says wants=count → trinity not called even if llm provided.
    'How many books did I read' is pure cardinal-count (not temporal)."""
    llm = _StubLLM(_ok_response("inference"))  # would be wrong if called
    q = "How many books did I read?"
    base = analyze(q)
    assert base.wants == "count", f"premise broken: {base.wants}"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "count"
    assert llm.calls == 0


def test_high_confidence_regex_date_skips_trinity():
    llm = _StubLLM(_ok_response("count"))
    q = "How many years older am I than when I graduated from college?"
    base = analyze(q)
    assert base.wants == "date", f"premise broken: {base.wants}"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "date"
    assert llm.calls == 0


def test_high_confidence_regex_inference_skips_trinity():
    llm = _StubLLM(_ok_response("count"))
    q = "What might I consider as a career path?"
    base = analyze(q)
    assert base.wants == "inference", f"premise broken: {base.wants}"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "inference"
    assert llm.calls == 0


# === Trinity escalation on lookup queries ===


def test_lookup_upgrade_to_detail_consistent():
    """Both trinity calls return 'detail' → upgrade applied."""
    llm = _StubLLM(_ok_response("detail"))
    q = "Which city is John excited to have a game at?"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "detail"  # upgraded from lookup
    assert llm.calls == 2  # retry-consistency


def test_lookup_upgrade_to_inference_consistent():
    llm = _StubLLM(_ok_response("inference"))
    q = "What other exercises can help John with his basketball performance?"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "inference"


def test_lookup_no_upgrade_when_trinity_returns_lookup():
    """Both calls return 'lookup' (consistent but no upgrade) → stays lookup."""
    llm = _StubLLM(_ok_response("lookup"))
    q = "What book did Tim get in Italy?"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "lookup"


# === Inconsistency / failure → fall back to regex ===


def test_inconsistent_picks_falls_back_to_regex():
    """Call 1 says 'detail', call 2 says 'inference' → fall back to lookup."""
    llm = _SequenceStubLLM([_ok_response("detail"), _ok_response("inference")])
    q = "Which city is John excited about?"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "lookup"
    assert llm.calls == 2


def test_both_calls_unparseable_falls_back():
    """Both calls return invalid JSON → fall back to regex."""
    llm = _StubLLM("not valid json {")
    q = "Which city is John excited about?"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "lookup"


def test_invalid_wants_string_falls_back():
    """Trinity returns gibberish wants like 'foo' → fall back."""
    llm = _StubLLM({"final_answer": "x", "confidence": 0.5,
                    "wants": "frobozz", "stances": []})
    q = "Which city is John excited about?"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "lookup"


# === Upgraded signature consistency ===


def test_upgraded_signature_recomputes_answer_shape():
    """When wants upgrades from lookup → detail, answer_shape recomputes."""
    llm = _StubLLM(_ok_response("detail"))
    q = "Which city is John excited about?"  # LoCoMo single-hop, regex → lookup
    base = analyze(q)
    assert base.wants == "lookup", f"premise broken: {base.wants}"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "detail"
    # answer_shape for detail/lookup query about a city → recomputed
    # (exact value depends on _answer_shape_for; just verify it ran)
    assert sig.answer_shape == _answer_shape_for_helper(q, "detail")


def _answer_shape_for_helper(q: str, wants: str) -> str:
    """Mirror attention._answer_shape_for behavior for assertion."""
    from radiomind.core.attention import _answer_shape_for
    return _answer_shape_for(q, wants)


def test_upgraded_signature_preserves_focus():
    """Trinity upgrade keeps the regex-extracted focus entity."""
    llm = _StubLLM(_ok_response("detail"))
    q = "What is John's favorite color?"
    sig = analyze_with_trinity(q, llm=llm)
    assert sig.wants == "detail"
    # focus extracted by regex on "what is X's Y" pattern (or None) — just
    # verify it's the same as base.focus, not lost in upgrade
    assert sig.focus == analyze(q).focus
