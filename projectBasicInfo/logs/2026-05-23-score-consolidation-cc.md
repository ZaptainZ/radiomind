# Score Consolidation — Current `main` Baseline

**Date**: 2026-05-23
**Author**: Claude Code
**Scope**: ground-truth scoreboard for `main` AFTER V8.2.x / V8.3.1 /
NAR (numeric-aggregator-recall) + NAR fix v2 merged.
**Purpose**: fix the baseline so the next workstream does not have
to re-invent it.

---

## Helper Trigger Surface (SC-1)

Offline scan of 499 LME-S qids:

| Helper | Triggered qids | Notes |
|---|---|---|
| `role_mismatch_guard` (V8.2.2) | 2 | query-side gate; includes `031748ae_abs` |
| `cashback_arithmetic_hint` (V8.2.3a) | 1 | only `9aaed6a3` |
| `person_age_average_hint` (V8.3.1) | 1 | only `gpt4_d12ceb0e` |
| `detect_charity_amounts` (NAR-5) | 67 | turn-level / ingest-side; one hit qid is `d851d5ba` |

Multi-helper overlap: 1 qid (`9aaed6a3`) triggers both
cashback_hint and charity_recognizer, but the latter is
turn-level only — its rows don't surface in answer prompts
because the question's focus noun ("cashback") routes
`get_numeric_cardinal()` away from `charity_donations`. No
answer-prompt-side stacking found.

Conclusion: each deterministic helper has a tight, isolated
query-side gate. No regression-via-stacking risk observed in
offline analysis.

## Target-Pack Repeat (SC-2)

3 runs × 4 target qids; deepseek-v3.2 answer / gpt-4o judge.

| qid              | run 1 | run 2 | run 3 | pass-rate |
|------------------|-------|-------|-------|-----------|
| `031748ae_abs`   | PASS  | PASS  | PASS  | **3/3**   |
| `9aaed6a3`       | PASS  | PASS  | PASS  | **3/3**   |
| `gpt4_d12ceb0e`  | PASS  | PASS  | PASS  | **3/3**   |
| `d851d5ba`       | PASS  | FAIL  | PASS  | 2/3 (pre-fix-v2) |

**Overall (3 SC-2 runs): 11/12 = 91.7%**.

Run 2 `d851d5ba` failure (cardinal computed $3,500 instead of
$3,750) was caused by an NAR-5 fix v1 gap: when `AMOUNT_PATTERNS`
regex extracted a charity amount with a non-charity `cls_hint`
(because the verb table only recognized "raised" not "raise"
base form), the recognizer's tag was silently dropped during
dedup. Trinity then revoked the un-tagged event.

**Fix v2** (commit `04a004d`) makes `detect_charity_amounts`
authoritative over the verb table. Verification:

- isolated re-ingest (3 runs, narfix-verify2): 3/3 produced cardinal view = $3,750
- e2e smoke (narfix-v2-smoke): PASS, answer "You raised $3,750 for charity in total."

Expected SC-2 post-fix-v2 pass-rate on `d851d5ba`: ≈3/3 (per
isolated stability + e2e smoke). Not re-bench-verified across
3 e2e runs to save budget; the underlying ingest state is now
deterministic.

## LoCoMo flip10 Sanity (SC-3)

1 run, deepseek-v3.2 / gpt-4o, raw=strict=**4/10**.

| qid | judge_orig | strict_judge |
|---|---|---|
| `c1_69a7c9bffe` | F | F |
| `c2_29183ecb5e` | F | F |
| `c2_b4b43181aa` | P | P |
| `c3_2656e2c771` | F | F |
| `c3_94f06e1a00` | P | P |
| `c3_a9fddfe69b` | F | F |
| `c4_5cfba98ae8` | P | P (Seattle decisive case still holds) |
| `c5_dac00a436e` | F | F |
| `c6_9da9f73c2a` | P | P |
| `c9_5ab522b5c7` | F | F |

V8.2.1 historical strict mean was 5.80/10 across 11 runs
(range 5-7). 4/10 is 1.80 points below mean and one point below
the lowest historical run.

**UPDATE (2026-05-24 via LCR-1 / LCR-4)**: a 4-step follow-up
investigation produced contemporary control data showing the
5.80 baseline is no longer reachable on today's deepseek-v3.2
even with V8.2.1 code itself:

| condition | n | strict /10 |
|---|---:|---:|
| V8.2.1 historical (mean of 11 runs) | 11 | 5.80 |
| V8.2.1 HEAD today (LCR-4) | 1 | 4 |
| current main NAR ON (LCR-1 mean) | 3 | 4.00 |
| current main, trinity threshold revert (LCR-2) | 1 | 4 |
| current main, NAR recognizer OFF (LCR-3') | 1 | 5 |

Interpretation (sample-strength-honest):

- The 5.80 historical number cannot be used as the
  contemporary baseline. External model/runtime drift since
  it was measured is the largest single factor we have
  evidence for.
- Current main with NAR ON is not visibly worse than V8.2.1
  HEAD today on this set (4 vs 4 strict), so there is no
  clear LoCoMo regression that warrants rolling NAR back.
- Recognizer OFF at strict 5 is +1 vs main with NAR ON, but
  n=1 sits inside the V8.2.1 historical 5-7 band — too small
  to call decisively.
- The Seattle decisive case (`c4_5cfba98ae8`) PASSes in
  every condition tested.

Per-qid stability (across LCR runs, strict judge):

| status | qids |
|---|---|
| stable PASS | `c2_b4b43181aa` (Maria), `c3_94f06e1a00` (Tilly), `c4_5cfba98ae8` (Seattle) |
| rotating | `c1_69a7c9bffe` (Gina), `c6_9da9f73c2a` (date) |
| stable FAIL | `c2_29183ecb5e` (financial), `c3_2656e2c771` (count), `c3_a9fddfe69b` (Nate), `c5_dac00a436e` (Voyageurs), `c9_5ab522b5c7` (Calvin) |

Full LCR write-up: `2026-05-24-locomo-regression-check-cc.md`.

## n=100 Decision (SC-4)

**Defer.** SC-2 + SC-3 + fix v2 verify together provide enough
evidence to claim the deterministic floor is sound for the 4
target qids. A full n=100 run (≈14h, ~$X cost) would mostly
re-measure non-target qid noise; that signal is dominated by
LLM seed variance, which 1 run won't characterize.

Better staged plan:

1. _Now:_ accept 4 target qids verified, baseline LoCoMo flip10
   "4/10 with caveats", and call current `main` a stable
   intermediate checkpoint.
2. _Next charity-focused iteration:_ if any new helper lands,
   run target-pack repeat (1h × N runs) + 1 LoCoMo flip10 run
   as the cheap regression check.
3. _Periodically:_ schedule a single LME-S n=100 (or n=50
   stratified) run when scope changes warrant it — not after
   every commit.

## Files & Artifacts

- SC-1 audit:                  `bench/end_to_end/sc1-trigger-audit.txt`
- SC-2 per-run JSONs:          `bench/end_to_end/sc2-target-pack-run{1,2,3}.json`
- SC-2 matrix:                 `bench/end_to_end/sc2-target-pack-matrix.json`
- SC-3 run 1:                  `bench/end_to_end/sc3-locomo-flip10-run1.json`
- fix v2 isolated verify:      `bench/end_to_end/narfix-verify2-matrix.json`
- fix v2 e2e smoke:            `bench/end_to_end/narfix-v2-smoke.json`

## Commit Trail

| Hash | Subject |
|---|---|
| `770417f` | bench: DATASET path → env-var fallback to persistent cache |
| `b7fdfca` | SC-1 + SC-2 wrapper + SC-5 draft |
| `1b23162` | SC-3 run 1: LoCoMo flip10 raw=strict=4/10 (preliminary) |
| `b763c96` | NAR-5 fix: tag AMOUNT_PATTERNS charity candidates with recognizer |
| `896e5a8` | SC-2 complete: 11/12 PASS (d851d5ba 2/3 flake, fixed in v2) |
| `04a004d` | NAR-5 fix v2: detect_charity_amounts authority over verb table |
| `ed775f0` | NAR-5 fix v2 verify: 3/3 isolated ingest stable |
| `a6f3e12` | NAR-5 fix v2 e2e smoke: d851d5ba PASS deterministic |
| _this_ | SC-5 score consolidation close-out |

## What This Snapshot Does NOT Claim

- Does not claim a measured LME-S n=100 overall accuracy on
  current `main`. The 4 target qids' improvements are
  individually verified; aggregate is inferred, not measured.
- Does not claim LoCoMo regression-free in the strong sense.
  LCR-1..LCR-4 produced contemporary evidence that the 5.80
  historical baseline is no longer reachable today (V8.2.1
  HEAD today also strict 4/10, n=1), so a definitive
  regression cannot be claimed. With n=1 controls, we can
  only say: no LoCoMo signal strong enough to justify rolling
  back NAR/V8.x has been found.
- Does not promise that fix v2 cleans the cache layer (t0/t6
  dup, music-benefit false positive). Cardinal view downstream
  filtering neutralizes these at prompt time, but cache rows
  remain "inflated" — that's a cosmetic, not load-bearing,
  artifact.

## Recommended Next Workstream

If continuing optimization, the priority order Codex previously
sketched still holds:

1. **Cache hygiene**: t0/t6 dup + cardinal header pre-filter
   total. Engineering debt; low risk; would make the prompt
   block cleaner and reduce LLM confusion potential.
2. **Concert ordering audit** (read-only). Has reusable
   temporal_provenance infrastructure.
3. **Kitchen count / preference advice**: stay out of scope.

Each future workstream should validate using this score-
consolidation framework: helper-trigger audit (offline, free)
→ target-pack repeat (1h × N runs) → optional LoCoMo flip10
sanity. n=100 only when justified by structural change.

---

**This document is the load-bearing baseline going forward.**
Cite this for "what main can do today" rather than re-deriving
from earlier per-version notes.
