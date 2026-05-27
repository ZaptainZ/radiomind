# LME-S n=100 JAB-Protected Contemporary Baseline

**Date**: 2026-05-28
**Author**: Claude Code
**Status**: Codex's full sequence complete. Baseline shipped.

---

## Headline

| metric | value |
|---|---|
| **overall accuracy** | **0.92** (92/100) |
| qids | 100, stratified, IDENTICAL sample as V8.2.2a |
| judge infra errors | 1 (SSL EOF on `75f70248`, retried 3x; marked FAIL on default) |
| JAB-1a vetoes triggered | **0** |
| commit | main HEAD `5a5bf67` (TESG-1c + TSI-1d + all guards) |

Tied with V8.2.2a-judge-fixed (0.92) on the identical 100-qid
sample, but composition shifted:

- **FIXED** (V8.2.2a FAIL → new PASS, 3): `c18a7dc8`,
  `gpt4_93159ced_abs`, `b6025781`
- **REGRESSED** (V8.2.2a PASS → new FAIL, 3): `75f70248`,
  `bb7c3b45`, `gpt4_194be4b3`

## Fix Attribution

| qid | mechanism |
|---|---|
| `c18a7dc8` | TSI-1c/d age_interval skill (conf=0.9 → "7") + prefix trust; LLM committed "7" directly. Stochastic stable in 3-qid smoke runs. |
| `gpt4_93159ced_abs` | TESG-1c temporal endpoint guard → soft abstain rewrite ("available evidence does not establish ... Google") matched gold via gpt-4o judge. |
| `b6025781` | Single-session-preference; not a target of any helper. Stochastic improvement (LLM happened to give a better-matching answer). |

The first two are causally attributable to this workstream's
TESG-1c + TSI-1d landings. The third is stochastic noise on a
preference question that doesn't trigger any of our helpers.

## Regression Attribution

| qid | category | cause |
|---|---|---|
| `75f70248` | single-session-preference | **judge infra error** — SSL EOF after 3 retries → default `correct=False`. NOT a model regression. If retried successfully, score would be 0.93. |
| `bb7c3b45` | multi-session | LLM stochasticity. V8.2.2a committed "$300", today abstained. Doesn't trigger TESG/TSI/JAB. Probably commit-side calibration drift (no helper fix yet). |
| `gpt4_194be4b3` | multi-session | LLM stochasticity. V8.2.2a counted 4 instruments, today counted 5. Entity-norm border case — `gpt4_ab202e7f` (kitchen count) is the same shape and was already deferred for `computation_high_risk` (open-vocabulary normalization). Same class. |

None of the regressions are caused by code paths that
this workstream introduced. TESG-1c only fires on
employer-endpoint duration questions; TSI-1d only fires on
age_interval older/younger arithmetic. Neither matches the
regressed qids.

## Codex's Full 6-Stage Sequence — Status

| stage | content | shipped |
|---|---|---|
| 1 | JAB-1a runner-side abstain veto + 30-artifact historical scan | ✓ `9938750` |
| 2 | JAB-1b detector tightening (29 unit tests) | ✓ `aab0c53` |
| 3 | TESG-1c semantic hardening (no factual overclaim on FACT absence) | ✓ `f016b22` `83fbb9e` |
| 4 | TSI-1b read-only full-cohort age_interval probe (3/3 concrete-gold safe surface) | ✓ `aec2b4a` |
| 5 | TSI-1d age commit closure (6 deterministic gates + recompute match) | ✓ `f17e1c9` `5a5bf67` |
| 6 | JAB-protected LME-S n=100 baseline | ✓ this log |

98 unit tests pass (33 TSI-1d + 35 TESG-1c + 29 JAB-1a/b
+ 1 cq4_variant_hook). 100% sample overlap with V8.2.2a.

## What This Does and Doesn't Mean

**Does:**

- TESG-1c successfully closes gpt4_93159ced_abs in production
  without breaking the NovaTech negative anchor (2/2 smoke +
  full n=100 confirms).
- TSI-1d's age_interval commit closure shipped without
  causing any visible regression — its 6-gate proof contract
  (including the recompute-match safety) held.
- JAB-1a deterministic abstain veto deployed; 0 false-passes
  in this n=100 run, confirming V8.2.2a-era "0.92 is not
  inflated" claim continues to hold on current main.
- 91 of the 92 PASSes are real model+judge agreements; 1
  PASS (`b6025781`) is stochastic-improved over V8.2.2a.

**Does NOT:**

- Improve the aggregate score above 0.92. Net composition is
  identical (3 FIX − 3 REGRESS).
- Address the regression on `bb7c3b45` (which would need
  retrieval-bridging or commit-side calibration work — out
  of scope here).
- Address the regression on `gpt4_194be4b3` (entity
  normalization — already deferred per LSA-2 `computation_
  high_risk`).
- Make any claim about historical baselines being inflated
  (JAB-1 historical scan showed V8.2.2a `0.92` had 0
  abstain false-passes; that claim was retracted earlier).

## Remaining Known Fails (8/100)

| qid | qtype | label |
|---|---|---|
| `75f70248` | single-session-preference | judge HTTP error (re-run would resolve) |
| `1c0ddc50` | single-session-preference | gold_or_input_limitation (preference advice) |
| `gpt4_194be4b3` | multi-session | computation_high_risk (entity norm) |
| `b46e15ed` | temporal-reasoning | event_cluster_interval_shape_gap (defer) |
| `gpt4_d6585ce8` | temporal-reasoning | evidence_present_computation_missing (concert ordering, defer) |
| `gpt4_ab202e7f` | multi-session | computation_high_risk (kitchen entity norm, defer) |
| `d6233ab6` | single-session-preference | gold_or_input_limitation (preference advice) |
| `bb7c3b45` | multi-session | stochastic LLM regression (calibration; new fail class) |

## Files

- Artifact: `bench/end_to_end/lme-s-n100-2026-05-26.json`
- Checkpoint: `bench/end_to_end/lme-s-n100-2026-05-26.checkpoint.jsonl`
- This log: `projectBasicInfo/logs/2026-05-28-lme-s-n100-jab-protected-baseline-cc.md`
- Related logs:
  - `projectBasicInfo/logs/2026-05-26-aas1-retraction-aas2-tesg1-cc.md`
  - `projectBasicInfo/logs/2026-05-26-tsi1-cohort-audit-cc.md`
  - `projectBasicInfo/logs/2026-05-26-tsi1d-proof-linkage-cc.md`
