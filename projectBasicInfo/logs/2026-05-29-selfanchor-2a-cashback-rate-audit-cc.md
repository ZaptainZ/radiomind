# SelfAnchor-2a — Cashback Rate Anchor Recall Audit (Read-Only)

**Date**: 2026-05-29
**Author**: Claude Code
**Status**: Read-only audit complete. Confirms the cashback RATE
anchor is the same recall-recoverable shape as paid/age. Gate
for SelfAnchor-2b: PASS (trigger surface = 1, store-recoverable,
merchant-scoping safe). No code change here.

---

## Why

SelfAnchor-1c surfaced `9aaed6a3` (cashback) as a real
regression: this run's retrieve missed the SaveMart-scoped 1%
rate; Phase-1.5a's merchant scoping correctly refused Walmart+
2% (`rate_merchant_mismatch`) → abstain → FAIL on concrete gold
$0.75. Hypothesis: the merchant-scoped cashback RATE is a 4th
self-anchor recall gap (anchor in store user-turn, missed by
retrieve top-200). 2a tests this rigorously.

## Stage 0 — trigger pre-screen + raw ground truth

Full LME-S 500 scanned with the cashback trigger
(`_query_triggers`).

**Trigger surface = 1 qid: `9aaed6a3`.** (Narrower than paid=2,
age=3.) The entire benchmark has exactly one cashback-earning
question.

Raw-haystack rate scan (user turns) for 9aaed6a3:

| turn | rate | scope |
|---|---|---|
| `answer_353d3c6d_2_t0` | **1%** | **SaveMart-scoped** ("I have a membership there and can earn 1% cashback on all purchases") |
| `c846422a_1_t4/t6/t8` | 2% | Walmart+ (competing merchant — distractor) |

The correct anchor (SaveMart 1%) is a first-person user turn.
The competing Walmart+ 2% rate is the negative that merchant
scoping must reject.

## Stage 2 — store vs retrieve (reused diagnose sandbox)

Ran `_find_cashback_rate_scoped` separately on the store's
user-turn layer vs retrieve top-200 user turns:

| source | user turns | scoped rate | reason |
|---|---|---|---|
| **store** | 269 | **0.01** | — (SaveMart 1% recovered from `answer_353d3c6d_2_t0`) |
| **retrieve top-200** | 27 (10%) | **None** | `rate_merchant_mismatch` (only Walmart+ 2% present; SaveMart 1% not retrieved this run) |

VERDICT: **store recovers SaveMart 1% = True; retrieve misses it
= True.** Same recall mechanism as paid/age — FACT events
dominate retrieve top-200, user-turn recall ~10%, the
merchant-scoped rate ranks out.

Cross-run evidence: the Phase-1.5a diagnose snapshot
(`diagnose-9aaed6a3.json`, cashback proof `rate=0.01,
computed=$0.75`) shows a run where retrieve DID surface the 1%
rate. So 9aaed6a3's pass/fail is retrieve-recall-dependent —
exactly the fragility class SelfAnchor addresses.

## Matrix

| qid | anchor | in_store | in_retrieve | regex_recoverable | risk |
|---|---|---|---|---|---|
| `9aaed6a3` | SaveMart 1% cashback rate | ✓ | ✗ (this run) | ✓ (merchant-scoped) | LOW |

## Risk assessment (for SelfAnchor-2b)

| risk | assessment |
|---|---|
| competing merchant in store (Walmart+ 2%) gets mis-applied | LOW — store scan MUST use `_find_cashback_rate_scoped` (1.5a merchant scoping), which already returns `rate_merchant_mismatch` when only a competing-merchant rate exists |
| hypothetical recommendation rate ("you could get 3%") | LOW — 1.5a ownership/generic guards already exclude these |
| trigger surface blast radius | MINIMAL — 1 qid in the entire benchmark |
| proof traceability | REQUIRED — 2b must emit source_turn_id + quote + scan_scope, same as paid/age |
| over-reach (scanning when rate IS retrievable) | LOW — supplement only fires when the cashback helper already refused for a rate-missing reason |

## Gate decision

PASS. Trigger surface is the narrowest of all self-anchor forms
(1 qid). The anchor is store-recoverable. The 1.5a merchant
scoping makes the store scan safe against the obvious negative
(Walmart+ 2%). The fix is architecturally identical to the
shipped paid/age store scans.

Important framing: SelfAnchor-2b would NOT add a new closure. It
makes an EXISTING closure (`9aaed6a3` cashback, shipped V8.2.3a)
retrieve-recall-STABLE. Its 2026-05-26 n=100 PASS was luck of the
retrieve draw; 1c caught the unlucky draw.

## SelfAnchor-2b spec (NOT implemented)

`scan_cashback_rate_user_turns(mind, domain, merchant)` in
`self_anchor.py`:
- read store user turns (role=user / `[user]` prefix only)
- call `_find_cashback_rate_scoped(user_texts, merchant)` —
  reuse 1.5a scoping verbatim
- on a single scoped rate, return
  `SelfAnchorProof(kind="cashback_rate", value=rate,
  source_turn_id, quote, scan_scope="user_turns;merchant=<m>")`
- else None

Wiring: `cashback_arithmetic_hint(question, mems, mind, domain)`
— when the retrieve-side scoped finder returns None for a
rate-missing reason (`no_cashback_rate_in_memories`,
`rate_merchant_mismatch`, `rate_anchor_unscoped`,
`rate_not_supporting_target_merchant`) AND merchant is known AND
the spend amount IS present, run the store scan. Hint-only.

Verification plan: unit tests (SaveMart 1% recovered; Walmart+
2%-only still refuses; ambiguous multi-rate refuses; assistant
echo rejected) → 9aaed6a3 e2e smoke (a few runs, since the bug is
stochastic) → confirm no n=100.

Requires go-ahead — 2a closes here.

## Files

- This log; data inline (stage-2 ran on reused sandbox
  `/tmp/rm-diagnose-qid-9aaed6a3`, no new artifact)
- Prior: `2026-05-29-selfanchor-1c-consolidation-cc.md`
  (where the 9aaed6a3 regression first surfaced)
