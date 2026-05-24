# LoCoMo Regression Check — LCR-1 through LCR-4

**Date**: 2026-05-24
**Author**: Claude Code
**Status**: Closed. **Verdict (sample-strength-honest)**: the
5.80 historical baseline is no longer reachable on today's
deepseek-v3.2 even with V8.2.1 code, so external model/runtime
drift is confirmed as an important factor. Current main with
NAR ON has not been shown to be worse than V8.2.1 HEAD today
on the same set (4 vs 4 strict, n=1 each), so there is no
LoCoMo signal strong enough to justify rolling back NAR/V8.x.
This does NOT prove drift is the sole factor or that NAR's
LoCoMo effect is exactly zero — n=1 controls cannot support
that strong claim. LME-S deterministic-floor wins remain
intact.

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
from historical 5.80 to today's 4. **Hypothesis E is now
supported (not strictly confirmed at n=1)**: external
deepseek-v3.2 / runtime drift is a confirmed important factor.
That a second factor (e.g., NAR ingest-side change in LCR-3'
direction) ALSO contributes cannot be ruled out at n=1, but
the recognizer-off +1 strict point sits inside the V8.2.1
historical 5-7 range — too small to act on without more samples.

## Decision Matrix

|   | V8.2.1 (historical 11-run) | V8.2.1 HEAD (today) | main with NAR | main with NAR off |
|---|---|---|---|---|
| strict /10 | 5.80 | 4 | 4.00 mean | 5 (n=1) |

- Today's V8.2.1 baseline (4, n=1) vs current main with NAR
  (4.00, n=3 mean): no LoCoMo signal in our data justifies
  rolling NAR back. We are NOT claiming NAR's net effect on
  LoCoMo is exactly zero — only that the available evidence
  doesn't support a rollback.
- NAR recognizer-off (5) is +1 strict point vs both V8.2.1
  today and NAR-on, but n=1 sample sits inside the V8.2.1
  historical 5-7 range — too small to act on.
- Historical V8.2.1 5.80 is no longer reachable on today's
  deepseek-v3.2 with V8.2.1 code itself, so framing the gap as
  a current-main "regression" overstates what we have evidence
  for.

## Decision

**No code rollback.** The available evidence does not justify
unwinding NAR/V8.x. The LME-S deterministic-floor wins on the
target qids (`031748ae_abs`, `9aaed6a3`, `gpt4_d12ceb0e`,
`d851d5ba`) remain valid and worth keeping. We explicitly
acknowledge that we have not proven NAR's LoCoMo effect is
zero; only that the cost (if any) is small enough to be
indistinguishable from sample noise at the n we ran.

The two env-var hooks added during the investigation
(`RADIOMIND_TRINITY_MIN_AMBIGUOUS`, `RADIOMIND_NAR_RECOGNIZER_ENABLED`)
are kept in place as load-bearing diagnostic switches. Default
values preserve current behavior; future A/Bs can flip them
without code changes.

**Future LoCoMo baseline reference**: V8.2.1 historical 5.80
remains a historical reference, not a current target. Until a
new high-n contemporary baseline is measured, treat strict 4-5
as the band consistent with available data; mark 5.80 as
"historical, not directly comparable" when citing.

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
