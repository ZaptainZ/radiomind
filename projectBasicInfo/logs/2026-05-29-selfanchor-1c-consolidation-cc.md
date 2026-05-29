# SelfAnchor-1c — Consolidation (Close-Out)

**Date**: 2026-05-29
**Author**: Claude Code
**Status**: Consolidation complete. 11-qid target-pack run (no
n=100). diagnose_qid surfaces SelfAnchor proof. Overview synced.
One real regression found (`9aaed6a3` cashback rate recall) —
documented, not fixed in this step.

---

## Step 1 — target-pack (11 qids, no n=100)

`bench/end_to_end/selfanchor-1c-targetpack.json`. Overall 8/11.

| qid | kind | correct | reading |
|---|---|---|---|
| `031748ae_abs` | role guard | ✓ | abstain correct |
| `9aaed6a3` | cashback | **✗** | **real regression** — SaveMart 1% rate not retrieved this run; scoped finder correctly refused to use Walmart+ 2% → LLM abstained → FAIL on concrete gold |
| `d851d5ba` | charity sum | ✓ | $3,750 (answer field retains a `<mem_thinking>` prefix — cosmetic, judge still PASS) |
| `gpt4_d12ceb0e` | person_age + SelfAnchor | ✓ | self age 32 recovered by store-scan → 59.6 |
| `c18a7dc8` | age_interval + SelfAnchor | ✓ | current age 32 recovered, gate-7 32−25=7 |
| `gpt4_93159ced_abs` | TESG | ✓ | Google abstain correct |
| `gpt4_93159ced` | TESG neg-anchor | ✓ | NovaTech "4 years 9 months" preserved |
| `bb7c3b45` | SavingsHint + SelfAnchor | ✓ | paid $200 recovered → $300 |
| `e25c3b8d` | negative | ✗ | expected — retail same-item proximity gate refuses (SavingsHint-1a behavior) |
| `157a136e` | negative | ✗ | expected — input limitation (no user age in data) |
| `6613b389` | negative | ✓ | before-mode event interval computed = 2 via the normal path; SelfAnchor did NOT mis-fire (trigger-face confirmed self-scan → None) |

### Interpretation

- **6 of 7 deterministic closures stable** (role / charity /
  person_age / age_interval / TESG / SavingsHint). SelfAnchor's
  3 recoverable qids all PASS — store-scan recovery is stable.
- **negatives behave correctly**: no SelfAnchor mis-fire. The 2
  failing negatives (`e25c3b8d`, `157a136e`) fail for their own
  documented reasons, NOT because the supplement did something
  wrong. `6613b389` passes via its normal path.
- Target-pack accuracy (0.7273) is NOT a quality metric — the
  pack deliberately includes 3 negatives expected to fail/abstain.
  The signal is per-qid byte-path correctness, not the aggregate.

## The one real regression: 9aaed6a3 (cashback rate recall)

Mechanism: `9aaed6a3` needs the SaveMart-scoped **1% rate**
(retrieve ranks 56-57 in the Phase-1.5a diagnose run) plus the
$75 spend. This run's retrieve did not surface the 1% rate; only
the Walmart+ 2% rate was present. Phase-1.5a's merchant-scoped
finder **correctly refused** to apply Walmart's 2% to a SaveMart
question (`rate_merchant_mismatch`) → no hint → LLM abstained →
FAIL on the concrete gold $0.75.

This is the SAME shape SelfAnchor-1a found for paid/age anchors:
**the helper's needed anchor (here the merchant-scoped cashback
RATE) lives in a store user-turn but ranks out of retrieve
top-200.** It is a 4th self-anchor-like recall gap.

- It is NOT a Phase-1.5a defect — the scoped refusal is the
  correct safe behavior (better to abstain than apply the wrong
  merchant's rate).
- It IS a recall-recoverable case: the SaveMart 1% rate is in the
  store; a `scan_cashback_rate_user_turns(mind, domain, merchant)`
  supplement (mirroring the paid/age scans) would recover it.
- SelfAnchor-1b scope was deliberately locked to paid/current-age/
  self-age (the 3 audited RECOVERABLE forms). cashback rate was
  not in that audit, so it was correctly NOT added on the fly.

9aaed6a3 passed the 2026-05-26 n=100 baseline because that run's
retrieve happened to surface the 1% rate. Its stability is
retrieve-recall-dependent — exactly the fragility class this whole
SelfAnchor line is about.

**Recommendation**: a future `SelfAnchor-2` (or `CashbackRate-
recall`) would extend the store-scan supplement to the cashback
rate anchor, gated the same way (helper already triggered +
merchant-scoped + single rate missing from retrieve). NOT opened
here — needs its own 1a-style audit first (trigger surface,
merchant-scope safety, negative set) before any code.

## Step 2 — diagnose_qid SelfAnchor proof (done)

`_probe_self_anchor` added: when a helper refuses for a
self-anchor reason, the diagnostic runs the matching store-scan
and reports `recovered / value / source_turn_id / scan_scope /
quote` — the same proof fields production carries. Verified on
c18a7dc8 (current_age RECOVERED 32.0 from answer_2e2085fa_2_t8).
Committed 77b492b. Tool chain (Phase 1 / 1.5 / 1b) now closes.

## Step 3 — overview sync (done)

`01_PROJECT_OVERVIEW.md`: bb7c3b45 reclassified to "closed by
SavingsHint-1b + SelfAnchor paid-anchor store-scan"; SelfAnchor-1b
section added. Committed 77b492b.

## Decision

SelfAnchor-1c consolidation closes. Net state:
- SelfAnchor-1b is sound: 3/3 recoverable qids PASS, negatives
  clean, no global retrieval change.
- One adjacent recall gap surfaced (`9aaed6a3` cashback rate),
  documented as a candidate for a separately-audited future
  workstream — NOT a defect in shipped code.

Per the agreed sequencing, Phase 2 (Proof registry) is next: it
consolidates the now-validated `source_turn_id / quote /
scan_scope / refusal_reason` contract that grew organically
across cashback / savings / age / TESG / SelfAnchor, rather than
each helper carrying a parallel diagnose_* function.

## Files

- Target-pack: `bench/end_to_end/selfanchor-1c-targetpack.json`
- Diagnose tool: `bench/end_to_end/diagnose_qid.py` (1c step 2)
- Overview: `projectBasicInfo/01_PROJECT_OVERVIEW.md` (1c step 3)
- This log; prior: `2026-05-29-selfanchor-1a-audit-cc.md`,
  `2026-05-29-selfanchor-1b-closeout-cc.md`
