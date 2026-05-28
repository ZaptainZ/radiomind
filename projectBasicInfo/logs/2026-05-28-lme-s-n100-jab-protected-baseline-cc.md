# LME-S n=100 JAB-Protected Contemporary Baseline

**Date**: 2026-05-28
**Author**: Claude Code
**Status**: Codex's full sequence complete. Baseline shipped.

---

## Headline

| metric | value |
|---|---|
| **overall accuracy (raw)** | **0.93** (93/100) — after `75f70248` rejudge |
| **overall accuracy (initial run)** | 0.92 (92/100) — included 1 judge SSL infra error |
| qids | 100, stratified, IDENTICAL sample as V8.2.2a |
| judge infra errors (post-rejudge) | 0 |
| JAB-1a vetoes triggered | **0** |
| commit | main HEAD `5a5bf67` + rejudge patch (this log's commit) |

Initial n=100 run had 1 unjudged record (`75f70248` SSL EOF
on the judge's third retry). Per Codex 2026-05-28: that does
NOT directly translate to a PASS — the actual answer might
or might not match gold. Resolution: rejudge the single record
through gpt-4o on the saved (gold, answer) pair.

Rejudge result: **`75f70248` → PASS**. Updated raw accuracy
**0.93**.

**Caveat on the rejudge semantics** (Codex 2026-05-28
confirmed): the answer covers gold's primary
cat/dander cause, but does NOT cover the gold's secondary
"recent deep clean stirred up dust" sub-cause. gpt-4o judge
accepted as semantically equivalent on the primary claim.
This is a judge interpretation call, not a verbatim match.
The PASS is therefore the judge's call, not a tight gold-
to-answer overlap — recorded here so future reviewers know
the basis.

### Final score range vs V8.2.2a

| | v822a-judge-fixed | new (post-rejudge) | delta |
|---|---|---|---|
| score | 0.92 (92/100) | **0.93** (93/100) | **+1** |
| judge_failed | 0 | 0 | — |
| judged_accuracy | 0.92 | 0.93 | — |

Composition (v822 vs new, identical 100-qid sample):

- **FIXED** (V8.2.2a FAIL → new PASS, 3): `c18a7dc8`,
  `gpt4_93159ced_abs`, `b6025781`
- **REGRESSED** (V8.2.2a PASS → new FAIL, 2): `bb7c3b45`,
  `gpt4_194be4b3`
- **Initially-unjudged-then-confirmed-PASS** (1): `75f70248`

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
| `75f70248` | single-session-preference | initial run: judge SSL EOF after 3 retries. **Rejudged 2026-05-28 → PASS**. Not a regression; was a transient infra fail. |
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
- Net **+1** vs V8.2.2a (0.92 → 0.93) attributable to 3 FIX
  − 2 REGRESS:
  - 2 FIX directly causal to this workstream's helpers
    (c18a7dc8, gpt4_93159ced_abs)
  - 1 FIX stochastic (b6025781, preference advice — not
    target of any helper, LLM happened to give a better
    matching answer this run)
  - 2 REGRESS not caused by helpers (bb7c3b45, gpt4_194be4b3
    — both outside TESG/TSI/JAB trigger surface)

**Does NOT:**

- Push the score significantly above V8.2.2a (the +1 delta is
  within stochastic noise band for a 100-qid sample). The
  claim is "no regression + 2 target closures shipped", not
  "RadioMind is now meaningfully stronger at LME-S".
- Address the regression on `bb7c3b45` (which would need
  retrieval-bridging or commit-side calibration work — out
  of scope here).
- Address the regression on `gpt4_194be4b3` (entity
  normalization — already deferred per LSA-2 `computation_
  high_risk`).
- Make any claim about historical baselines being inflated
  (JAB-1 historical scan showed V8.2.2a `0.92` had 0
  abstain false-passes; that claim was retracted earlier).

## Remaining Known Fails (7/100, post-rejudge)

| qid | qtype | label |
|---|---|---|
| `1c0ddc50` | single-session-preference | gold_or_input_limitation (preference advice) |
| `gpt4_194be4b3` | multi-session | computation_high_risk (entity norm) |
| `b46e15ed` | temporal-reasoning | event_cluster_interval_shape_gap (defer) |
| `gpt4_d6585ce8` | temporal-reasoning | evidence_present_computation_missing (concert ordering, defer) |
| `gpt4_ab202e7f` | multi-session | computation_high_risk (kitchen entity norm, defer) |
| `d6233ab6` | single-session-preference | gold_or_input_limitation (preference advice) |
| `bb7c3b45` | multi-session | stochastic LLM regression (calibration; new fail class) |

## Bench Hygiene Patches

### Codex 2026-05-28 P2 (resume judge stats)

Runner's checkpoint resume rebuilt `correct` / `n` /
`per_type` from checkpoint records but did NOT rebuild
`judge_errors` / `judge_n` / `model_correct`. After resume
the top-level fields were the post-resume window only.

Fix in `bench/end_to_end/run_longmemeval_mem0.py` resume
loop: also accumulate judge stats during checkpoint replay.

### Codex 2026-05-28 second-pass P1 + P1 + P2 (rejudge schema sync)

First-pass rejudge wrote `overall_accuracy` and
`judged_accuracy` but left `raw_accuracy` stale at 0.92,
and added a new `by_question_type` field that diverged from
the canonical `by_type` schema. Checkpoint still held the
pre-rejudge SSL FAIL.

Fix in `bench/end_to_end/rejudge_single_qid.py`:
- Update `raw_accuracy` alongside `overall_accuracy`.
- Recompute `by_type` in the canonical schema
  `{qtype: {n, accuracy}}` (float, not count).
- Drop legacy `by_question_type` field if present.
- Add `--checkpoint` option to patch the matching qid line
  in the checkpoint so canonical state mirrors the artifact.

One-shot normalize pass run on
`bench/end_to_end/lme-s-n100-2026-05-26.json` +
`.checkpoint.jsonl`. Post-normalize:

- `raw_accuracy = overall_accuracy = judged_accuracy = 0.93`
- `judge_errors = 0`, `judge_n = 100`
- `by_type.single-session-preference.accuracy = 0.875` (14/16)
- `by_type.knowledge-update.accuracy = 1.0` (16/16)
- `by_type.multi-session.accuracy = 0.8333` (15/18)
- `by_type.temporal-reasoning.accuracy = 0.8824` (15/17)
- `by_question_type` field removed
- Checkpoint line for `75f70248` patched
  (`correct=true, judge_failed=false,
  rejudged_2026_05_28=true`)

## Files

- Artifact (post-rejudge): `bench/end_to_end/lme-s-n100-2026-05-26.json`
- Checkpoint: `bench/end_to_end/lme-s-n100-2026-05-26.checkpoint.jsonl`
- Rejudge utility: `bench/end_to_end/rejudge_single_qid.py`
- Runner resume fix: `bench/end_to_end/run_longmemeval_mem0.py`
- This log: `projectBasicInfo/logs/2026-05-28-lme-s-n100-jab-protected-baseline-cc.md`
- Related logs:
  - `projectBasicInfo/logs/2026-05-26-aas1-retraction-aas2-tesg1-cc.md`
  - `projectBasicInfo/logs/2026-05-26-tsi1-cohort-audit-cc.md`
  - `projectBasicInfo/logs/2026-05-26-tsi1d-proof-linkage-cc.md`
