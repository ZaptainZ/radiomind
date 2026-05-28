# V8.2 → V8.4 Cycle Close-Out

**Date**: 2026-05-28
**Author**: Claude Code
**Status**: Cycle complete. Benchmark chasing paused. Main
HEAD `45fd15e`, origin sync.

---

## What This Cycle Delivered

### Deterministic floor — 7 target qids shipped, all with audit-passed gates

| qid | family | helper | gate type |
|---|---|---|---|
| `031748ae_abs` | leadership/IC role mismatch | `role_mismatch_guard` (V8.2.2a) + `maybe_rewrite_with_guard` (V8.2.2b) | prefix + commit-side rewrite |
| `9aaed6a3` | cashback arithmetic | `cashback_arithmetic_hint` (V8.2.3a) | hint-only |
| `gpt4_d12ceb0e` | kin-average age | `person_age_average_hint` (V8.3.1) | hint-only |
| `d851d5ba` | charity sum | `detect_charity_amounts` (NAR) | ingest-side |
| `c18a7dc8` | age delta with explicit at-age-N | `age_interval` skill + TSI-1d commit closure | prefix + 6-gate + recompute rewrite |
| `gpt4_93159ced_abs` | temporal endpoint unsupported | TESG-1c | prefix + soft rewrite |
| `bb7c3b45` | savings on named item | `savings_arithmetic_hint` (V8.4-A) | hint-only |

7 closures in total, each with:
- a pre-implementation audit (trigger surface, anchor
  stability, negative deterministic-rejectability)
- a strict gate (no LLM semantic, no synonym, no
  cross-family expansion, no "I saved $X" direct extract)
- unit tests covering positive + negative + format

### Evaluation hygiene layer

| component | function |
|---|---|
| `jab1_abstain_veto.py` | deterministic veto when LLM judge passes a canonical-abstain response against a concrete gold |
| runner resume fix | rebuild `judge_errors / judge_n / model_correct` from checkpoint, not just `n / correct / per_type` |
| `rejudge_single_qid.py` | normalize artifact schema (`raw_accuracy`, canonical `by_type`) + sync checkpoint with rejudge result |
| historical false-pass scan | 30-artifact offline scan confirming V8.2.2a `0.92` carries 0 abstain false-passes |

### Contemporary baseline

| metric | value |
|---|---|
| LME-S n=100 (a2a-practice, deepseek-v3.2 / gpt-4o, post-rejudge) | **0.93** raw = overall = judged |
| sample identical to V8.2.2a-judge-fixed | 100/100 overlap |
| judge_errors | 0 |
| JAB-1a vetoes triggered | 0 |
| delta vs V8.2.2a | +1 (3 FIX − 2 REGRESS), within 100-qid stochastic band |

The +1 is NOT claimed as "RadioMind got materially better
at LME-S". The intellectually honest claim is:

- 2 target closures attributable to this cycle's helpers
  (`c18a7dc8`, `gpt4_93159ced_abs`) shipped without
  helper-caused regression elsewhere
- 1 stochastic improvement on a preference-advice qid
  (`b6025781`) not in any helper's trigger surface
- 2 stochastic regressions on qids outside helper triggers
  (`bb7c3b45`, `gpt4_194be4b3`)
- post-SavingsHint expected +1 on `bb7c3b45`; not
  re-measured because n=100 cost is high and the result
  wouldn't validate architectural value at 1-qid scale

### Remaining 7 fails — final classification

| qid | label | scope |
|---|---|---|
| `1c0ddc50`, `d6233ab6` | preference advice | out of scope (subjective, judge-elastic) |
| `gpt4_194be4b3` (instruments), `gpt4_ab202e7f` (kitchen) | open-vocab entity normalization | out of scope (needs typed inventory / typed-event architecture, not regex stacking) |
| `b46e15ed` | event_cluster_interval_shape_gap | **single-qid confirmed** (LME-S 500 cohort scan finds only 1 elapsed-since-cluster qid); permanent defer |
| `gpt4_d6585ce8` | ordered_event_sequence | **cohort = 7** (trips / museums / sports / airlines / concerts); sort step deterministic via session_date, extraction step open-vocab gating; **candidate for future OrderedEventList workstream** — middle-weight, not a narrow helper |
| `bb7c3b45` | savings on item | **closed by SavingsHint-1b** (target smoke 2/2) |

## Architectural Rules Hardened This Cycle

Codex's reviews across the cycle distilled 6 rules that
must hold for any future helper:

1. **Pre-implementation audit before ship.** Trigger
   surface size, anchor stability, negative
   deterministic-rejectability. No LLM-side test stands
   in for an audit.

2. **Strict gate before commit.** Helpers default to
   hint-only. A commit-side rewrite requires multiple
   independent deterministic proofs (V8.2.2b: role
   mismatch + over-commit detection. TSI-1d: 6 gates
   including recompute-match. TESG-1c: positive employer
   evidence absence + over-commit detection).

3. **Absence of evidence is not negative evidence.**
   FACT extraction can miss raw turns; store scan is
   capped. "User has never said X" can only be asserted
   when there is explicit negative or future-plan
   textual evidence; otherwise wording stays at
   "available evidence does not establish X".

4. **No cross-family expansion at first ship.**
   SavingsHint stays at retail−paid; doesn't extend to
   coupon/discount/percent-off. TESG stays at employer
   endpoint; doesn't extend to event endpoint (deferred
   sub-shape). TSI stays at older/younger arithmetic;
   doesn't extend to date-since/before.

5. **Evaluation hygiene is bench-side responsibility.**
   Concrete-gold + canonical-abstain → deterministic
   veto. Runner resume must preserve judge stats.
   Artifact + checkpoint must stay schema-consistent.
   Don't lean on historical PASS as evidence — past
   judge / LLM stochasticity can have given fake passes.

6. **N=100 is for consolidation, not validation.** A
   1-qid helper's architectural value is not visible at
   100-qid scale (within stochastic band). Run target
   smoke after each ship; defer n=100 until 2–3 closures
   have accumulated.

## What This Cycle Did NOT Do

- Did not push the n=100 score meaningfully above V8.2.2a.
  The +1 is real but within noise. We don't claim
  RadioMind is materially stronger at LME-S.
- Did not address open-vocabulary entity normalization
  (instruments, kitchen items count). That needs a typed
  inventory layer, not regex.
- Did not address preference advice. That's subjective
  and judge-elastic; tuning here risks turning the
  system into a bench-specific advice generator.
- Did not implement `OrderedEventList`. The 7-qid cohort
  is a real signal but extraction is open-vocab; a
  separate architectural workstream is warranted, not a
  V8.2-style narrow helper.

## Next Phase Recommendation (paused, not in progress)

User's direction (2026-05-28): pause benchmark chasing.
The two reasonable forward paths are:

1. **`OrderedEventList-1a` read-only architecture audit**.
   - Targets the 7-qid cohort (trips / museums /
     sports / airlines / concerts).
   - Goal: design a structured event-list layer with
     attendance-verb filter + typed event extraction +
     session_date sort.
   - Middle-weight engineering. NOT a narrow regex helper.
   - Gate: extraction must work across all 7 qids with
     low FP rate; if it doesn't, abandon and pursue
     typed-event architecture instead.

2. **Non-bench product capability**.
   - Codify the deterministic-skills + support-aware
     commit gate + judge hygiene + artifact consistency
     patterns into the core architecture.
   - Focus on ingest / retrieval / tooling UX rather
     than 1-qid bench gains.

Both are paused. No new code work scheduled.

## Files Index

### Logs (chronological)

- `2026-05-25-lsa1-baseline-freeze-cc.md`
- `2026-05-25-lsa2-failure-inventory-cc.md`
- `2026-05-25-lsa3-existing-path-audit-cc.md`
- `2026-05-26-aas1-retraction-aas2-tesg1-cc.md`
- `2026-05-26-tsi1-cohort-audit-cc.md`
- `2026-05-26-tsi1d-proof-linkage-cc.md`
- `2026-05-28-lme-s-n100-jab-protected-baseline-cc.md`
- `2026-05-28-post-093-failure-family-audit-cc.md`
- `2026-05-28-savings-hint-1a-audit-cc.md`
- `2026-05-28-post-savings-remaining-fail-audit-cc.md`
- **`2026-05-28-v82-v84-cycle-closeout-cc.md`** (this log)

### Source

- `src/radiomind/core/role_mismatch_guard.py` (V8.2.2)
- `src/radiomind/core/arithmetic_hint.py`
  (V8.2.3a cashback + V8.4-A savings)
- `src/radiomind/core/typed_event_hint.py` (V8.3.1 person_age)
- `src/radiomind/refinement/numeric_aggregator.py` (NAR
  charity recognizer)
- `src/radiomind/skills/age_interval.py` (V6.3-A subject-
  neutral anchor + trinity escalation)
- `src/radiomind/core/age_interval_commit.py` (V8.4 TSI-1d)
- `src/radiomind/core/temporal_endpoint_guard.py` (V8.4 TESG-1c)

### Tests

- `tests/test_arithmetic_hint.py` (cashback)
- `tests/test_savings_arithmetic_hint.py` (savings)
- `tests/test_jab1_abstain_veto.py`
- `tests/test_temporal_endpoint_guard.py`
- `tests/test_age_interval_commit.py`

### Bench utilities

- `bench/end_to_end/run_longmemeval_mem0.py` (runner with
  resume-stat fix + JAB veto)
- `bench/end_to_end/rejudge_single_qid.py` (artifact-aware
  rejudge)
- `bench/end_to_end/jab1_abstain_veto.py` (shared detector)
- `bench/end_to_end/jab1_concrete_gold_abstain_scan.py`
  (historical scan)
- `bench/end_to_end/savings_hint_1a_audit.py` (trigger
  surface + 2-anchor audit)
- `bench/end_to_end/tsi1b_age_interval_cohort.py`
  (TSI cohort probe)

### Artifacts

- `bench/end_to_end/lme-s-n100-2026-05-26.json` (0.93
  post-rejudge baseline)
- `bench/end_to_end/lme-s-n100-2026-05-26.checkpoint.jsonl`
- `bench/end_to_end/jab1-false-pass-scan.json` (historical
  scan results)
- `bench/end_to_end/savings-hint-1a-audit.json` (audit)
- `bench/end_to_end/savings-hint-1b-smoke.json` (target
  smoke 2/2 PASS)
- `bench/end_to_end/tesg1c-e2e.json` (TESG-1c smoke 2/2 PASS)
- `bench/end_to_end/tsi1c-e2e.json` (TSI-1c smoke)
- `bench/end_to_end/tsi1d-e2e.json` (TSI-1d revalidation)
- `bench/end_to_end/tsi1b-cohort-probe.json` (age_interval
  3-qid cohort, all concrete gold)
