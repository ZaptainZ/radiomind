"""Phase2-1b: prove the unified ProofResult carrier holds the cashback proof
LOSSLESSLY and renders byte-identically to the live closure — without
changing any commit behavior.

Gate for 1b: resolve_cashback_proof's dict and cashback_proof_to_result's
ProofResult must be equivalent, and ProofResult.rendered must equal what
maybe_cashback_commit_closure actually commits. Uses the verbatim 9aaed6a3
haystack sentences (see test_cashback_closure_field_9aaed6a3.py).
"""
from __future__ import annotations

from radiomind.core.proof_result import ProofResult, Source
from radiomind.core.arithmetic_hint import (
    resolve_cashback_proof,
    cashback_proof_to_result,
    maybe_cashback_commit_closure,
)

QUESTION = "How much cashback did I earn at SaveMart last Thursday?"
ABSTAIN = "I don't have enough information to answer that."
AMOUNT_MEM = ("I went grocery shopping at SaveMart last Thursday and "
              "spent $75 on my purchase.")
RATE_MEM = ("By the way, SaveMart has this loyalty program where you "
            "get 1% cashback on all your purchases.")


def mem(s):
    return {"memory": s}


class _Entry:
    def __init__(self, content, role="user", turn_id="t0"):
        self.content = content
        self.metadata = {"role": role, "turn_id": turn_id}


class _Store:
    def __init__(self, entries):
        self._entries = entries

    def list_by_domain(self, domain, level=None, limit=None):
        return self._entries


class _Mind:
    def __init__(self, entries):
        self._store = _Store(entries)


REAL_MEMS = [mem(AMOUNT_MEM), mem(RATE_MEM)]


def test_adapter_is_lossless_vs_proof_dict():
    proof = resolve_cashback_proof(QUESTION, REAL_MEMS)
    assert proof is not None
    pr = cashback_proof_to_result(proof)
    assert isinstance(pr, ProofResult)
    # every field of the original dict is recoverable from the ProofResult
    assert pr.kind == "cashback"
    assert pr.subject == proof["merchant"]
    assert pr.inputs["amount"] == proof["amount"]
    assert pr.inputs["rate"] == proof["rate"]
    assert pr.value == proof["product"]
    assert pr.sources[0].turn_id == proof["rate_source_turn_id"]
    assert pr.sources[0].role == "rate"
    assert pr.scan_scope == proof["rate_scan_scope"]
    assert pr.recompute_ok is True
    assert pr.confidence is None


def test_adapter_rendered_matches_live_closure_bytes():
    # The carrier must render the EXACT string the closure commits.
    proof = resolve_cashback_proof(QUESTION, REAL_MEMS)
    pr = cashback_proof_to_result(proof)
    committed = maybe_cashback_commit_closure(QUESTION, REAL_MEMS, ABSTAIN)
    assert pr.rendered == committed
    assert pr.rendered == "You earned $0.75 in cashback at SaveMart."


def test_adapter_carries_store_scan_provenance():
    # SelfAnchor-2b run11 shape: rate resolved via store scan -> the
    # turn_id + scan_scope must survive into the ProofResult.
    amount_only = [mem(AMOUNT_MEM)]
    store = _Mind([_Entry(f"[user] {RATE_MEM}", turn_id="store-rate")])
    proof = resolve_cashback_proof(QUESTION, amount_only, mind=store, domain="d")
    assert proof is not None
    assert proof["rate_source_turn_id"] == "store-rate"
    pr = cashback_proof_to_result(proof)
    assert pr.sources[0].turn_id == "store-rate"
    assert pr.scan_scope == proof["rate_scan_scope"]
    assert pr.scan_scope is not None
    assert pr.value == 0.75


def test_proofresult_is_frozen():
    import dataclasses
    import pytest
    pr = cashback_proof_to_result(resolve_cashback_proof(QUESTION, REAL_MEMS))
    with pytest.raises(dataclasses.FrozenInstanceError):
        pr.value = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        pr.sources[0].turn_id = "x"  # type: ignore[misc]
