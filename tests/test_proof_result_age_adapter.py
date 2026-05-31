"""Phase2-1c: prove the unified ProofResult carrier holds the age_interval
proof — the real stress test for `sources: list[Source]` (dual provenance)
and `confidence` — and that the live closure renders byte-identically
through the adapter (no behavior change).

Uses the same known-good fixtures as test_age_interval_commit.py (the real
LongMemEval c18a7dc8 case: graduated at 25, now 32 → 7 years older).
"""
from __future__ import annotations

from radiomind.core.proof_result import ProofResult
from radiomind.core.age_interval_commit import (
    maybe_age_interval_commit_closure,
    age_interval_proof_to_result,
    _find_age_at_event,
    _find_current_age,
    _question_unit,
    _question_mode,
)

Q = "How many years older am I than when I graduated from college?"
ABSTAIN = "The information provided is not enough."
MEMS = [
    {"memory": "[user] I have a Bachelor's degree in Business "
               "Administration with a concentration in Marketing "
               "from the University of California, Berkeley, which "
               "I completed at the age of 25."},
    {"memory": "[user] As a 32-year-old Digital Marketing Specialist, "
               "I'm always looking for new learning resources."},
]
SECTION = (
    "STRUCTURED SKILL (age_interval, conf=0.90): trust this unless "
    "retrieval explicitly contradicts.\n"
    "- graduated from college → 2023-05-26\n"
    "- current age (store self-ID) → 32\n"
    "Computed answer: 7\n\n"
)


def _extracted():
    past_age, past_ev = _find_age_at_event(MEMS)
    current_age, cur_ev = _find_current_age(MEMS)
    return past_age, past_ev, current_age, cur_ev


def test_live_closure_output_equals_adapter_rendered():
    # The closure now renders FROM the adapter; bytes must be identical to
    # what the adapter produces for the same extracted proof.
    past_age, past_ev, current_age, cur_ev = _extracted()
    expected = age_interval_proof_to_result(
        skill_value=7, unit=_question_unit(Q), mode=_question_mode(Q),
        past_age=past_age, current_age=current_age,
        past_evidence=past_ev, current_evidence=cur_ev,
        current_scan_scope=None, confidence=0.90,
    )
    out = maybe_age_interval_commit_closure(Q, MEMS, ABSTAIN, SECTION)
    assert out == expected.rendered
    # and the existing exact-output guarantees still hold
    assert out.startswith("7 years.")
    assert "current age 32" in out and "past-event age 25" in out


def test_adapter_dual_source_and_fields():
    past_age, past_ev, current_age, cur_ev = _extracted()
    pr = age_interval_proof_to_result(
        skill_value=7, unit="years", mode="older",
        past_age=past_age, current_age=current_age,
        past_evidence=past_ev, current_evidence=cur_ev,
        current_scan_scope=None, confidence=0.90,
    )
    assert isinstance(pr, ProofResult)
    assert pr.kind == "age_interval"
    assert pr.value == 7
    assert set(pr.inputs) == {"past_age", "current_age", "mode"}
    assert pr.inputs["past_age"] == past_age == 25
    assert pr.inputs["current_age"] == current_age == 32
    assert pr.inputs["mode"] == "older"
    assert pr.subject is None
    assert pr.scan_scope is None
    assert pr.confidence == 0.90
    assert pr.recompute_ok is True
    # dual provenance — the reason `sources` is a list
    assert len(pr.sources) == 2
    at_age, current = pr.sources
    assert at_age.role == "at_age"
    assert at_age.turn_id is None          # strict regex yields no id
    assert at_age.quote == past_ev
    assert current.role == "current_age"
    assert current.turn_id is None         # retrieve path: no id
    assert current.quote == cur_ev


def test_adapter_store_scan_carries_turn_id_and_scope():
    pr = age_interval_proof_to_result(
        skill_value=7, unit="years", mode="older",
        past_age=25, current_age=32,
        past_evidence="at the age of 25", current_evidence="I am 32",
        current_scan_scope=("turn-xyz", "domain=people"), confidence=0.9,
    )
    assert pr.sources[1].turn_id == "turn-xyz"
    assert pr.scan_scope == "domain=people"
    assert "SelfAnchor store-scan: turn turn-xyz" in pr.rendered


def test_adapter_recompute_ok_reflects_arithmetic():
    ok = age_interval_proof_to_result(
        skill_value=6, unit="years", mode="younger",
        past_age=20, current_age=14, past_evidence="a", current_evidence="b",
        current_scan_scope=None, confidence=0.9,
    )
    assert ok.recompute_ok is True
    bad = age_interval_proof_to_result(
        skill_value=5, unit="years", mode="younger",
        past_age=20, current_age=14, past_evidence="a", current_evidence="b",
        current_scan_scope=None, confidence=0.9,
    )
    assert bad.recompute_ok is False
