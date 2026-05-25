# LSA-2 — LME-S n=100 Failure Inventory + 4-Class Label

**Date**: 2026-05-25
**Author**: Claude Code
**Status**: Read-only. No code change. Inventory closed.

---

## Setup

Loaded V8.2.2a-judge-fixed n=100 baseline (most contemporary)
plus V8.2.1 n=100 as comparator. Excluded the 4 shipped target
qids + dataset errata. 8 in-scope fails labeled per Codex's
4-class schema. Full record at
`bench/end_to_end/lsa2-failure-inventory.json`.

## In-Scope Fails (V8.2.2a baseline, 8 qids)

```
label                                  count
gold_or_input_limitation                   4
retrieve_missing                           2
commit_variance                            1
evidence_present_computation_missing       1
```

| qid | qtype | label | one-line reason |
|---|---|---|---|
| `1c0ddc50` | single-session-preference | gold_or_input_limitation | preference advice |
| `b46e15ed` | temporal-reasoning | retrieve_missing | LLM abstained on numeric delta |
| `b6025781` | single-session-preference | gold_or_input_limitation | preference advice |
| `c18a7dc8` | multi-session | retrieve_missing | LLM abstained on age delta |
| `d6233ab6` | single-session-preference | gold_or_input_limitation | preference advice (v8.3-audit) |
| `gpt4_93159ced_abs` | temporal-reasoning | commit_variance | gold = abstain, LLM over-committed |
| `gpt4_ab202e7f` | multi-session | gold_or_input_limitation | kitchen count, entity-norm (v8.3-audit) |
| `gpt4_d6585ce8` | temporal-reasoning | evidence_present_computation_missing | concert ordering (v8.3-audit) |

## LSA-3 Filter (per LSA-1 in-scope rules)

Codex's 4 mandatory conditions for an LSA-pilot:

1. Gold-bearing memory IS in retrieve top-K under default.
2. Answer derivable by deterministic operator over typed events.
3. Trigger expressible as a query-shape family.
4. Extends existing layer or matches the narrow-helper shape.

Applying per label:

- **gold_or_input_limitation (4 qids)** — fails condition 2
  (no deterministic operator yields preference / kitchen-count
  / nostalgic-advice). All 4 OUT.
- **retrieve_missing (2 qids)** — fails condition 1 by
  definition. Both are "retrieval-bridging-recall" family,
  which LSA-1 explicitly defers. Both OUT.
  - `c18a7dc8` is age-delta-shaped which superficially looks
    like person_age territory, but the gold relies on
    "graduation-year mention + current-year mention" being in
    the same retrieved context. If the relevant turns
    aren't in top-K (LLM-abstain suggests they aren't), the
    person_age skill can't bridge that gap; would need
    retrieval methodology first. OUT.
  - `b46e15ed` is months-delta between two charity events,
    similar shape. OUT.
- **commit_variance (1 qid)**: `gpt4_93159ced_abs` —
  gold is "not enough information" but the LLM committed.
  This is a calibration / abstain-gate problem, similar to
  V8.2.2b's canonical-abstain post-rewrite. Could in
  principle be extended (generalize "role mismatch" → "any
  presupposition violation"), but no clean narrow family
  guard exists across qids. Single-qid intervention
  forbidden. OUT.
- **evidence_present_computation_missing (1 qid)**:
  `gpt4_d6585ce8` — concert ordering, already V8.3-audit
  YELLOW. Surviving the filter is possible but the operator
  (multi-event-per-session + temporal resolution + ordering)
  is meaningfully larger than the four shipped helpers.

## LSA-3 Decision

**Passes the LSA-3 filter: 1 qid (`gpt4_d6585ce8`).**
**Passes the LSA-3 priority gate** (per LSA-1: amount aggregation >
rate multiplication > age arithmetic > exact ordering > entity-norm
count > preference): **YES** for "exact ordering" tier, but it's
the lowest-priority tier above the "do-not-pursue" ones.

## LSA-5 Recommendation

**Do NOT auto-open an LSA-5 pilot.** Justification:

- The one surviving candidate (concert ordering) is a tier-5
  shape (exact ordering); user-supplied priority lists tiers 1-3
  as preferred. We're below the priority bar.
- V8.3 audit already flagged this case as YELLOW with explicit
  "defer to V8.3.2 follow-up" — the present LSA-2 reaches the
  same conclusion via the same evidence.
- 4 of 8 fails are out-of-scope (gold/input/preference), 2 of 8
  are retrieval-bridging (excluded), 1 is calibration (no
  family guard).
- Opening a single-qid pilot with cost ≈ NAR (~3 weeks of
  read-only audit + impl + e2e) for a tier-5 shape would be
  worse cost/benefit than the deterministic-floor wins
  already shipped.

The LSA-2 inventory closes here with "no LSA-5 pilot recommended
on current baseline." If a future LME-S n=100 measurement on
current main reveals new fails outside this set, re-run LSA-2.

## Practical Outcome

After LSA-1 freeze + LSA-2 inventory + LSA-3 filter, the audit
trail says:

- Current main (post-V8.3.1 + NAR fix v2) has 4 shipped
  deterministic helpers covering 4 LME-S target qids.
- Remaining 8 fails on the most-contemporary baseline are NOT
  good candidates for new narrow deterministic helpers.
- Optimization on LoCoMo + LME-S has converged within the
  "narrow deterministic" frame.
- Next material gains require either retrieval-recall-bridging
  methodology (LLM-heavy) or moving to a different RadioMind
  component (Rust ingest, MCP / community / etc.).

## What This Does NOT Mean

- Does NOT prove the 4 fixed targets stay fixed forever.
  Future model drift (deepseek-v3.2 or successor) could
  re-flake them. The deterministic helpers are designed to
  insulate against this; smokes should be re-run on
  significant model changes.
- Does NOT prove no further narrow win exists. A new
  benchmark, new dataset, or a different qid sampling could
  surface a new amount-aggregation / rate-multiplication
  shape that fits.
- Does NOT close LME-S as a benchmark target — only the
  "narrow widget" optimization mode against the current
  V8.2.2a-judge-fixed n=100 baseline.

## Files / Commits

- Audit script: `bench/end_to_end/lsa2_lme_failure_inventory.py`
- Inventory JSON: `bench/end_to_end/lsa2-failure-inventory.json`
- LSA-1 baseline freeze: `projectBasicInfo/logs/2026-05-25-lsa1-baseline-freeze-cc.md`
- This log: `projectBasicInfo/logs/2026-05-25-lsa2-failure-inventory-cc.md`
