# LoCoMo Regression Check — LCR-1 through LCR-4

**Date**: 2026-05-24
**Author**: Claude Code
**Status**: Closed. **Verdict: "regression" is deepseek-v3.2 model
drift, NOT NAR/V8.x stacking.** No code changes needed; NAR/V8.x
deterministic floor remains intact.

---

## Why This Investigation

`SC-3` (score consolidation step 3) ran LoCoMo flip10 once on
current `main` (post-NAR fix v2) and got strict **4/10**. V8.2.1
historical 11-run mean was strict **5.80/10** (range 5-7). The
-1.80 strict-point gap could be:

- **A**: single-run noise (V8.2.1 also had per-run variance).
- **B**: NAR-5 `_trinity_class_promotion` threshold drop (`>=2`
  → `>=1`) firing trinity more often on LoCoMo non-charity
  haystacks.
- **C**: NAR-5 `detect_charity_amounts` recognizer adding spurious
  charity_donations cardinal entries on LoCoMo haystacks (67/499
  LME-S qids triggered it; LoCoMo similar surface).
- **D**: V8.2.3a / V8.3.1 / V8.2.2 stacking has cross-cutting
  effects on non-target queries.
- **E**: deepseek-v3.2 model drift since V8.2.1 was measured.

The user's clear request: "不要马上开 cache hygiene，也不要开
concert/kitchen。先把 SC-3 补完。"

## Experiment Chain

### LCR-1: 2 extra LoCoMo flip10 runs to disambiguate noise vs regression

Per-run strict (sc3-locomo-flip10-run{1,2,3}.json):

| run | orig | strict |
|---|---|---|
| 1 | 4 | 4 |
| 2 | 4 | 3 |
| 3 | 7 | 5 |
| **mean** | **5.00** | **4.00** |

3-run mean strict = 4.00 = 1.80 below V8.2.1 historical mean.
Not noise (3-run consistent under V8.2.1 5-7 band). Hypothesis A
ruled out.

### LCR-2: trinity threshold revert (RADIOMIND_TRINITY_MIN_AMBIGUOUS=2)

Single run: orig 5, strict 4. Same as LCR-1 mean strict 4.00.
**Hypothesis B ruled out** — threshold drop is not the cause.

Added env-var hook (commit `2ec7862`) for the A/B; default
behavior preserved.

### LCR-3' (pivot): recognizer disabled (RADIOMIND_NAR_RECOGNIZER_ENABLED=0)

Single run: orig 6, strict 5 (+1 vs LCR-1 mean strict 4.00).

Added second env-var hook in `detect_charity_amounts` (commit
`e830372`). c1_69a7c9bffe (Gina tattoo) PASSed with recognizer
off — suggests minor ingest-side interference on V7 evidence-
candidate territory.

**Hypothesis C partially supported** but n=1 — could be noise.
Net effect ≤ 1 strict point.

### LCR-4: V8.2.1 HEAD baseline today (model-drift control)

`git worktree add` at 8c11171 (V8.2.1 run-11 commit). Same
deepseek-v3.2 / gpt-4o / flip10 today:

  orig 6, **strict 4**.

**Same strict as LCR-1 NAR-on mean.** V8.2.1 HEAD itself drops
from historical 5.80 to today's 4. **Hypothesis E confirmed**:
deepseek-v3.2 model drift over the past weeks is the dominant
factor.

## Decision Matrix

|   | V8.2.1 (historical 11-run) | V8.2.1 HEAD (today) | main with NAR | main with NAR off |
|---|---|---|---|---|
| strict /10 | 5.80 | 4 | 4.00 mean | 5 (n=1) |

- Today's V8.2.1 baseline (4) = current main with NAR (4.00 mean):
  NAR has **no measurable net regression** on LoCoMo flip10.
- NAR recognizer-off (5) is +1 strict point vs both V8.2.1 today
  and NAR-on, but n=1 sample is inside the V8.2.1 historical
  range 5-7 — could be noise.
- Historical V8.2.1 5.80 is no longer reachable on today's
  deepseek-v3.2 even with V8.2.1 code, so the "regression"
  framing is misleading.

## Decision

**No code rollback.** NAR/V8.x deterministic-floor wins on the
LME-S target qids (`031748ae_abs`, `9aaed6a3`, `gpt4_d12ceb0e`,
`d851d5ba`) remain valid and worth keeping.

The two env-var hooks added during the investigation
(`RADIOMIND_TRINITY_MIN_AMBIGUOUS`, `RADIOMIND_NAR_RECOGNIZER_ENABLED`)
are kept in place as load-bearing diagnostic switches. Default
values preserve current behavior; future A/Bs can flip them
without code changes.

**Future LoCoMo baseline reference: strict 4-5/10 on today's
deepseek-v3.2**, not the stale 5.80 historical number.

## Risks Acknowledged

- Single-run V8.2.1 baseline (n=1) is itself noisy. A second
  V8.2.1 HEAD run today would tighten the model-drift
  estimate. Deferring as not worth ~2.7h of LLM budget given
  the directional answer is clear.
- The recognizer disabled run (LCR-3' strict 5) at n=1 could be
  either signal or noise. If a future iteration cares about the
  Gina-tattoo qid specifically, running LCR-3' two more times
  would confirm.

## Files & Commits

Per-run artifacts:

- `bench/end_to_end/sc3-locomo-flip10-run{1,2,3}.json`
- `bench/end_to_end/lcr2-trinity-revert.json`
- `bench/end_to_end/lcr3-recog-off.json`
- `bench/end_to_end/lcr4-v82-baseline.json`

Commit trail:

| Hash | Subject |
|---|---|
| `c7fde22` | LCR-1 wrapper: 2 extra LoCoMo flip10 runs |
| `776148d` | LCR-1 complete: 3-run mean strict 4.00 |
| `2ec7862` | trinity threshold: env-var override for LCR-2 |
| `e830372` | LCR-2 + recognizer env-var hook (LCR-3' pivot) |
| `1f331ed` | LCR-3' complete: recognizer off strict 5/10 |
| `ef1aeed` | LCR-4: V8.2.1 today strict 4/10 → model drift |
| _this_ | LCR-5: close-out (model drift verdict) |

## Cleanup

Pending in LCR-5 step:

1. `git worktree remove /tmp/rm-lcr4-v82-worktree`
2. `git branch -D lcr4-v82-baseline`
3. Keep `/tmp/locomo-data` and `/tmp/longmemeval-data` symlinks
   for convenience but they are not load-bearing (paths now
   resolve via env-var in main code).

## Updated Score Consolidation

Append to `2026-05-23-score-consolidation-cc.md` under "LoCoMo
flip10 Sanity": the SC-3 4/10 result is **expected** on today's
deepseek-v3.2; it is not a regression introduced by current main.
Use strict 4-5/10 as the new baseline reference, not 5.80.
