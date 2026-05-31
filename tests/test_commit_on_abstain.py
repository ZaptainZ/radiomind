"""Phase2-1d: direct unit tests for the shared commit_on_abstain gate.

The cashback closure now delegates its tail here; these pin the gate's
own contract independently of any closure: commit ONLY on a pure abstain
with a complete, recomputing proof; never overwrite a concrete answer.
"""
from __future__ import annotations

from radiomind.core.proof_result import ProofResult, Source, commit_on_abstain

ABSTAIN = "The information provided is not enough."


def _pr(recompute_ok=True, rendered="COMMITTED VALUE"):
    return ProofResult(
        kind="test", value=1, inputs={}, sources=[Source(None, None)],
        recompute_ok=recompute_ok, rendered=rendered,
    )


def test_commits_on_pure_abstain_with_valid_proof():
    assert commit_on_abstain(_pr(), ABSTAIN) == "COMMITTED VALUE"
    assert commit_on_abstain(_pr(), "I don't have enough information.") \
        == "COMMITTED VALUE"


def test_never_overwrites_concrete_answer():
    assert commit_on_abstain(_pr(), "You earned $5.") == "You earned $5."
    # hybrid (concrete + hedge) is not a pure abstain → unchanged
    assert commit_on_abstain(_pr(), "$5. Not enough info though.") \
        == "$5. Not enough info though."


def test_none_proof_leaves_abstain_unchanged():
    assert commit_on_abstain(None, ABSTAIN) == ABSTAIN


def test_recompute_failure_leaves_abstain_unchanged():
    assert commit_on_abstain(_pr(recompute_ok=False), ABSTAIN) == ABSTAIN


def test_is_commit_abstain_candidate():
    from radiomind.core.proof_result import is_commit_abstain_candidate
    assert is_commit_abstain_candidate(ABSTAIN) is True
    assert is_commit_abstain_candidate("I don't have enough information.") is True
    assert is_commit_abstain_candidate("You earned $5.") is False
    # hybrid (concrete + hedge) is not a pure abstain
    assert is_commit_abstain_candidate("$5. Not enough info though.") is False
