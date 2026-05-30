"""TrustClosure-1b unit tests — cashback commit closure.

Hard gate (Codex-locked):
  - only when llm_answer is a PURE canonical abstain
  - complete proof (merchant + retrieved amount + scoped rate)
  - recompute rate × amount == product
  - never overwrite a concrete answer
  - competing/conflicting rate, missing amount → bypass
"""
from __future__ import annotations

from radiomind.core.arithmetic_hint import (
    resolve_cashback_proof,
    maybe_cashback_commit_closure,
)


def mem(s):
    return {"memory": s}


# Fake store for SelfAnchor-2b store-scan path
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


def mind_with(*entries):
    return _Mind(list(entries))


Q = "How much cashback did I earn at SaveMart last Thursday?"
ABSTAIN = "The information provided is not enough."


# ── resolve_cashback_proof ──────────────────────────────────────────
class TestResolveProof:
    def test_rate_in_retrieve(self):
        mems = [mem("I spent $75 at SaveMart with my SaveMart 1% cashback card.")]
        p = resolve_cashback_proof(Q, mems)
        assert p is not None
        assert p["merchant"] == "SaveMart"
        assert p["amount"] == 75.0
        assert p["rate"] == 0.01
        assert p["product"] == 0.75
        assert p["rate_source_turn_id"] is None

    def test_rate_via_store_scan(self):
        mems = [mem("I spent $75 at SaveMart last Thursday."),
                mem("Walmart+ gives 2% cashback.")]
        store = mind_with(
            _Entry("[user] I spent $75 at SaveMart last Thursday.", turn_id="ta"),
            _Entry("[user] I have a SaveMart membership with 1% cashback on all purchases.", turn_id="tr"),
        )
        p = resolve_cashback_proof(Q, mems, mind=store, domain="d")
        assert p is not None
        assert p["rate"] == 0.01
        assert p["product"] == 0.75
        assert p["rate_source_turn_id"] == "tr"
        assert "merchant=SaveMart" in p["rate_scan_scope"]

    def test_amount_missing_none(self):
        mems = [mem("My SaveMart card gives 1% cashback.")]
        assert resolve_cashback_proof(Q, mems) is None

    def test_competing_only_none(self):
        mems = [mem("I spent $75 at SaveMart."),
                mem("Walmart+ gives 2% cashback.")]
        assert resolve_cashback_proof(Q, mems) is None  # no store, rate unresolved

    def test_no_trigger_none(self):
        assert resolve_cashback_proof("How much did I spend at SaveMart?",
                                      [mem("$75 SaveMart 1% cashback")]) is None


# ── closure: rewrite ────────────────────────────────────────────────
class TestClosureRewrites:
    def test_pure_abstain_committed(self):
        mems = [mem("I spent $75 at SaveMart with my SaveMart 1% cashback card.")]
        out = maybe_cashback_commit_closure(Q, mems, ABSTAIN)
        assert out == "You earned $0.75 in cashback at SaveMart."

    def test_store_scan_rate_committed(self):
        mems = [mem("I spent $75 at SaveMart last Thursday."),
                mem("Walmart+ gives 2% cashback.")]
        store = mind_with(
            _Entry("[user] I have a SaveMart membership with 1% cashback on all purchases.", turn_id="tr"))
        out = maybe_cashback_commit_closure(Q, mems, ABSTAIN, mind=store, domain="d")
        assert out == "You earned $0.75 in cashback at SaveMart."

    def test_idont_have_info_form(self):
        mems = [mem("I spent $75 at SaveMart with my SaveMart 1% cashback card.")]
        out = maybe_cashback_commit_closure(
            Q, mems, "I don't have enough information to answer.")
        assert "$0.75" in out


# ── closure: bypass ─────────────────────────────────────────────────
class TestClosureBypass:
    def test_concrete_answer_preserved(self):
        mems = [mem("I spent $75 at SaveMart with my SaveMart 1% cashback card.")]
        out = maybe_cashback_commit_closure(Q, mems, "You earned $0.75.")
        assert out == "You earned $0.75."  # not a pure abstain → unchanged

    def test_wrong_concrete_not_overwritten(self):
        # Even a WRONG concrete answer is preserved (closure only acts on abstain)
        mems = [mem("I spent $75 at SaveMart with my SaveMart 1% cashback card.")]
        out = maybe_cashback_commit_closure(Q, mems, "You earned $1.50.")
        assert out == "You earned $1.50."

    def test_competing_rate_only_bypass(self):
        mems = [mem("I spent $75 at SaveMart."),
                mem("Walmart+ gives 2% cashback.")]
        # no store → rate unresolved → bypass, abstain preserved
        out = maybe_cashback_commit_closure(Q, mems, ABSTAIN)
        assert out == ABSTAIN

    def test_conflicting_rates_bypass(self):
        mems = [mem("I spent $75 at SaveMart."),
                mem("My SaveMart card gives 1% cashback."),
                mem("Actually SaveMart now gives 3% cashback.")]
        out = maybe_cashback_commit_closure(Q, mems, ABSTAIN)
        assert out == ABSTAIN  # multiple_conflicting_rates → no rate → bypass

    def test_amount_missing_bypass(self):
        mems = [mem("My SaveMart card gives 1% cashback.")]
        out = maybe_cashback_commit_closure(Q, mems, ABSTAIN)
        assert out == ABSTAIN

    def test_hybrid_answer_not_pure_abstain(self):
        # concrete commitment + abstain phrase → not pure abstain → bypass
        mems = [mem("I spent $75 at SaveMart with my SaveMart 1% cashback card.")]
        out = maybe_cashback_commit_closure(
            Q, mems, "$0.75. Not enough info to be sure though.")
        assert "$0.75. Not enough" in out

    def test_no_trigger_bypass(self):
        out = maybe_cashback_commit_closure(
            "How much did I spend at SaveMart?",
            [mem("$75 SaveMart 1% cashback")], ABSTAIN)
        assert out == ABSTAIN
