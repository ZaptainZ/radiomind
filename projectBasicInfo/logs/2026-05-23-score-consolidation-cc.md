# Score Consolidation — Current `main` Baseline

**Date**: 2026-05-23
**Author**: Claude Code
**Scope**: snapshot of where `main` stands AFTER V8.2.x / V8.3.1 /
NAR (numeric-aggregator-recall) merged, BEFORE the next workstream.
**Purpose**: fix a "ground-truth scoreboard" so the next iteration
has a defensible baseline; avoid the situation where each new
workstream invents its own baseline.

---

## What's Different on `main` vs Previously-Tracked V8.2.1

| Component | Before V8.2.1 | After V8.2.1 | After NAR (`main` HEAD) |
|---|---|---|---|
| LongMemEval-S n=100 | V5 0.92 / V6.1.1 0.93 | V8.2.1 0.92 | _not re-measured (see SC-4)_ |
| LoCoMo flip10 strict mean | V5 mid-3 / V6.x 5-6 | V8.2.1 5.80/10 | (SC-3 measurement → _filled_) |
| Deterministic helpers (target qids) | none | 031748ae_abs | + 9aaed6a3 (V8.2.3a) + gpt4_d12ceb0e (V8.3.1) + d851d5ba (NAR) |
| Cardinal ingest reliability for d851d5ba | flaky | flaky | **stable** (NAR-6 5/5) |

## Trigger-face audit (SC-1)

[ TO BE FILLED ]

Coverage of the 4 deterministic helpers across LME-S 499 qids:

| Helper | Qids triggered | Notes |
|---|---|---|
| `role_mismatch_guard` (V8.2.2) | _N_ | _comment_ |
| `cashback_arithmetic_hint` (V8.2.3a) | _N_ | _comment_ |
| `person_age_average_hint` (V8.3.1) | _N_ | _comment_ |
| `detect_charity_amounts` (NAR-5) | 67 | NAR-8 confirmed no pollution path |

Multi-helper overlap (qids triggered by ≥ 2 helpers): _N_ qids.
Concerning overlaps (if any): _list_.

## Target-pack repeat (SC-2)

3 runs × 4 qids = 12 e2e calls. Deepseek-v3.2 answer / gpt-4o judge.

| qid | run 1 | run 2 | run 3 | pass-rate |
|---|---|---|---|---|
| `031748ae_abs` | _PASS/FAIL_ | _PASS/FAIL_ | _PASS/FAIL_ | _N/3_ |
| `9aaed6a3` | _PASS/FAIL_ | _PASS/FAIL_ | _PASS/FAIL_ | _N/3_ |
| `gpt4_d12ceb0e` | _PASS/FAIL_ | _PASS/FAIL_ | _PASS/FAIL_ | _N/3_ |
| `d851d5ba` | _PASS/FAIL_ | _PASS/FAIL_ | _PASS/FAIL_ | _N/3_ |

Overall: _N/12_ ( _%_ ).

Interpretation:
- 12/12 = the deterministic floor genuinely holds across LLM seed
  variance.
- < 12/12 = identify which qid still depends on LLM cooperation;
  investigate before claiming "