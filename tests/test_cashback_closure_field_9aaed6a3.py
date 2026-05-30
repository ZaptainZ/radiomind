"""TrustClosure-1c: deterministic field reproduction for qid 9aaed6a3.

test_cashback_commit_closure.py proves the closure with clean,
hand-authored SaveMart fixtures. This module instead pins it to the
*verbatim* memory sentences from the real LongMemEval-S haystack for
9aaed6a3 (longmemeval_data/longmemeval_s_cleaned.json), to prove the
parsers cope with the looser real phrasing ("get 1% cashback on all
your purchases", "spent $75 on my purchase"):

    Q:    "How much cashback did I earn at SaveMart last Thursday?"
    gold: "$0.75"
    mem:  "I went grocery shopping at SaveMart last Thursday and
           spent $75 on my purchase."
    mem:  "By the way, SaveMart has this loyalty program where you
           get 1% cashback on all your purchases."

Why this exists (1c verification — see
projectBasicInfo/logs/2026-05-30-trustclosure-1c-closeout-cc.md):
the 1c e2e smokes (tc1c r1-r5) were 5/5 PASS but the LLM committed on
its own every run, so the abstain->rewrite path was not naturally
exercised (it is stochastic). Rather than gate on catching a random
abstain, we prove deterministically that *if* the trust-gap recurs
(SelfAnchor-2b run11, tc1a r2 are the historical field captures), the
closure rescues it on the genuine memory text. Mem format and the
store-scan mock mirror test_cashback_commit_closure.py.
"""
from __future__ import annotations

from radiomind.core.arithmetic_hint import (
    resolve_cashback_proof,
    maybe_cashback_commit_closure,
)

QUESTION = "How much cashback did I earn at SaveMart last Thursday?"
ABSTAIN = "I don't have enough information to answer that."

# Verbatim from longmemeval_s_cleaned.json, qid 9aaed6a3.
AMOUNT_MEM = ("I went grocery shopping at SaveMart last Thursday and "
              "spent $75 on my purchase.")
RATE_MEM = ("By the way, SaveMart has this loyalty program where you "
            "get 1% cashback on all your purchases.")


def mem(s):
    return {"memory": s}


# Store-scan plumbing, mirrors test_cashback_commit_closure.py.
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


REAL_MEMS = [mem(AMOUNT_MEM), mem(RATE_MEM)]


def test_real_haystack_resolves_complete_proof():
    proof = resolve_cashback_proof(QUESTION, REAL_MEMS)
    assert proof is not None
    assert proof["merchant"] == "SaveMart"
    assert proof["amount"] == 75.0
    assert proof["rate"] == 0.01
    assert proof["product"] == 0.75


def test_real_haystack_pure_abstain_is_rescued_to_075():
    # The exact trust-gap: correct hint available, LLM abstains anyway.
    out = maybe_cashback_commit_closure(QUESTION, REAL_MEMS, ABSTAIN)
    assert out == "You earned $0.75 in cashback at SaveMart."


def test_real_haystack_concrete_answer_never_overwritten():
    # No regression on the path the 5/5 e2e runs actually took.
    out = maybe_cashback_commit_closure(
        QUESTION, REAL_MEMS, "You earned $0.75.")
    assert out == "You earned $0.75."


def test_real_haystack_store_scan_supplies_rate_when_retrieve_lacks_it():
    # SelfAnchor-2b run11 shape: amount in retrieve, rate only in store.
    amount_only = [mem(AMOUNT_MEM)]
    store = mind_with(_Entry(f"[user] {RATE_MEM}", turn_id="store-rate"))
    out = maybe_cashback_commit_closure(
        QUESTION, amount_only, ABSTAIN, mind=store, domain="d")
    assert "$0.75" in out
