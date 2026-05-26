# TSI-1d — Proof Linkage + 157a136e Archive

**Date**: 2026-05-26
**Author**: Claude Code
**Status**: TSI-1d proof linkage shipped. 157a136e archived as
`kin_age_delta_input_gap`. Pre-n=100 gate per Codex.

---

## Why This Was Needed

Codex 2026-05-26 (third TSI review) raised three P1 issues:

1. **TSI-1c's proof gate was too loose.** Original gates checked
   "some memory has age-at-event" AND "some memory has current-
   age" but did not verify those values are the same anchors the
   skill used. With multiple age events in retrieval, an unrelated
   event could authorize a numeric rewrite.

2. **157a136e was not properly archived.** It's a `kin_age_delta`
   skill-recall gap (skill didn't fire), distinct from TSI-1c
   trust-gap territory. The earlier write-up implicitly conflated
   the two.

3. **Parsing rendered `temporal_section` text is fragile.** Any
   wording change to `SkillResult.prefix()` would silently disable
   the gate. Acceptable as bench-side fix, not production
   architecture.

## TSI-1d Changes

### Proof linkage (P1)

`maybe_age_interval_commit_closure` now extracts anchor VALUES
from matched evidence and independently recomputes the delta:

```
past_age   = _find_age_at_event(memories)  → integer N1
current_age = _find_current_age(memories)  → integer N2
recomputed = (N2 − N1) if mode=="older" else (N1 − N2)
if recomputed != skill_value:
    return llm_answer  # reject — gate fails
```

Additionally:

- Mode-restricted to `older` / `younger` (other modes use date
  arithmetic — outside the recompute scope; rewrite stays
  dormant for `since`/`before`/`after`/`apart`).
- Skill answer must parse as a non-negative integer.
- Source quotes for both anchors are inserted into the rewritten
  output so reviewers can verify the arithmetic.

### Architectural note (P3)

The parse-from-rendered-text wiring is documented in source as a
benchmark-side fix. A future architectural pass should thread
typed `SkillResult` (with anchor list + source proofs) through
`run_temporal_precision` and the runner so the gate consumes
structured data. Out-of-scope for TSI-1d.

### 157a136e archive (P2)

Read-only raw-evidence scan of `157a136e`'s haystack
(251 user turns):

- Grandma age: **75** (explicit — "My grandma's 75th birthday
  celebration", verified in `answer_8de18468_2_t0/2/8`).
- User current age: **NOT explicit**. Only fuzzy
  `"I'm still getting used to being in my 30s"`
  (`answer_8de18468_1_t0`). No "I'm 32 / I just turned 32 / I'm
  32 years old" anywhere.

Gold=43 requires user_age=32 (75 − 43 = 32). Since the user's
exact age is not text-grounded, the answer is NOT
deterministic-derivable from the haystack. This matches the
"gold or input limitation" pattern — defer.

Status: **archived as `kin_age_delta_input_gap`**. Distinct
from age_interval trust gap. No further work in TSI scope.

## Tests

| count | description |
|---|---|
| 27 → 33 | TSI-1c/d age_interval_commit |
| 35 | TESG-1c temporal_endpoint_guard |
| 29 | JAB-1a/b abstain_veto |
| **97 → 98** total | all pass |

New TSI-1d tests:

- `test_rewrite_contains_source_proof`: rewrite output contains
  source quotes proving the arithmetic.
- `test_younger_mode_works`: younger mode arithmetic (N1 − N2)
  verified.
- `test_skip_when_recompute_does_not_match_skill`: skill claims
  X but recompute gives Y → rewrite must NOT fire. Critical
  false-positive safety.
- `test_skip_when_since_mode`, `test_skip_when_before_mode`:
  modes outside recompute scope stay dormant even with full
  backing evidence.
- `test_skip_when_non_integer_skill_answer`,
  `test_skip_when_negative_skill_answer`: defensive integer
  parsing.

## E2e validation

Pending — will run the 3-qid e2e after this commit to confirm
no regression vs the prior TSI-1c run.

## Outstanding

- 3-qid e2e revalidation (NovaTech-style smoke pattern, but on
  age_interval cohort: c18a7dc8 / 157a136e / 6613b389)
- After e2e clean → JAB-protected LME-S n=100 baseline (per
  Codex's full sequence)

## Files

- `src/radiomind/core/age_interval_commit.py` (rewrite proof
  linkage)
- `tests/test_age_interval_commit.py` (33 cases)
- `projectBasicInfo/logs/2026-05-26-tsi1d-proof-linkage-cc.md`
  (this log)
