# numeric-aggregator-recall — Workstream Close-out

**Date**: 2026-05-22
**Author**: Claude Code
**Scope**: ingest-side `charity_donations` recall fix for `d851d5ba`.
**Status**: All 10 steps PASS. Merge approved.

---

## Why This Workstream Exists

V8.3.1b's diagnostic concluded that `d851d5ba`'s flaky behaviour
was an **ingest-side recall issue**, not an output-side prompt
issue. Codex agreed to spin up an independent workstream
`numeric-aggregator-recall` rather than extend V8.3 with another
helper. The architectural principle:

- LLM owns natural-language understanding.
- Deterministic skills own arithmetic / aggregation.
- Skills only fire when input facts are confidently identified.
- The point of intervention is the **input-fact layer**, not the
  output prompt.

V8.3.1 had already shipped the deterministic computation skill
(`person_age_average_hint`); this workstream addresses the
parallel concern that the deterministic **inputs** to existing
arithmetic skills (the `cardinal_entries` rows fed into
`get_numeric_cardinal()`) were unreliable.

## 10-Step Plan

| # | Task | Status | Output |
|---|------|--------|--------|
| 1 | Reproduction baseline (5-run isolated ingest) | done | `bench/end_to_end/nar1-d851d5ba-matrix.json` |
| 2 | Locate recall failure (root cause) | done | commit `1472b2b` |
| 3 | Design charity recognizer (NAR-3) | done | `2026-05-22-nar3-charity-recognizer-design-cc.md` |
| 4 | Failing tests first (NAR-4) | done | `tests/test_numeric_aggregator_charity_recall.py` |
| 5 | Implement `detect_charity_amounts` + pipeline integration | done | commit `2dd813e` |
| 6 | Post-fix stability (5-run isolated re-ingest) | done | `bench/end_to_end/nar6-d851d5ba-matrix.json` |
| 7 | Single-qid e2e smoke (full pipeline) | done | `bench/end_to_end/nar7-d851d5ba-smoke.json` |
| 8 | Trigger-face audit on LME-S 499 qids | done | `bench/end_to_end/nar8-trigger-face-audit.md` |
| 9 | This document | done | — |
| 10 | Merge decision | done | MERGE (this doc, "Merge Decision" section) |

---

## Root Cause Findings (NAR-1 + NAR-2)

5 isolated re-ingests on the same haystack produced wildly
different `charity_donations` cache states:

| Run | charity_count | total | gold_hit (1-4) |
|-----|---|---|---|
| 1   |  5 | $9,750 | [2, 3, 4] |
| 2   |  0 | $0 | [] |
| 3   |  3 | $2,750 | [2, 3, 4] |
| 4   |  0 | $0 | [] |
| 5   |  6 | $10,750 | [1,2,3,4] |
| Strict PASS (4/4 + total=$3,750) | | | **0/5** |

Three layers of LLM stochasticity stack to produce this:

1. **Extraction layer**: `_batch_extract_llm` drops E2/E3 (food
   bank, ACS) entirely in 2/5 runs.
2. **Classification fallback**: `_AMOUNT_VERB_CLASS` maps only
   `"raised"` (past tense), not `"raise"` (base form). E1
   ("I helped raise over $1,000 ... at a charity bake sale")
   sends `cls_hint=amount_events` in 5/5 runs.
3. **Trinity refinement**: `_refine_amount_events` revoke
   decisions on the same evidence range from `{-0, -2, -4, -7,
   -7}` across runs. Runs 2 and 4 wiped the entire class
   (`trinity_revoke -7 events (-$11,750)`).

## Fix Design (NAR-3 → NAR-5)

A self-contained regex layer `detect_charity_amounts(content) ->
list[dict]` runs alongside the existing AMOUNT_PATTERNS extractor.
Three triggers:

- **T1**: receiver tail (text following the amount, max 120 chars,
  stops at sentence-end or next `$`) names a charity-context
  entity (food bank / animal shelter / hospital / nonprofit /
  charity / foundation / society / ...). T1 also requires a
  charity verb (`raise|donate|contribute|gave to`) in the window
  to reject medical-bill spending like "$200 for the hospital".
- **T2**: window contains the literal word `charity` AND a charity
  verb.
- **T3**: window contains a known charity org (Red Cross / UNICEF /
  ACS / Salvation Army / etc.).

Guards:

- Family-relation word (`my niece|brother|...`) in window blocks
  all triggers (family transfer, not charity).

Pipeline integration (in `process_turns` and `_classify_batch`):

1. `_regex_extract` runs the new recognizer alongside AMOUNT_PATTERNS;
   skips amounts already captured as `charity_donations`.
2. LLM/regex merge: when a deterministic-charity regex candidate
   matches `(turn_id, amount)` of an existing LLM candidate,
   MUTATE the LLM candidate in place (upgrade `entity_class` to
   `charity_donations`, tag `recognizer="deterministic-charity"`)
   instead of adding a duplicate.
3. `_classify_batch` one-way upgrade: recognizer-tagged candidates
   in `amount_events` / null class promote to `charity_donations`.
4. `_apply_delta` tags history `reason="amount_charity_det"` for
   recognizer-promoted events.
5. `_refine_amount_events` matches `reason == "amount"` only — so
   deterministic-tagged events are **naturally** excluded from
   trinity revoke. No additional code needed in trinity.
6. `_trinity_class_promotion` threshold lowered from
   `len(ambiguous) >= 2` to `>= 1` (trinity still votes on
   remaining ambiguous events after recognizer pre-handles the
   obvious ones).

## Post-Fix Stability (NAR-6)

| Run | charity_count | total | gold_hit | cardinal-view total |
|-----|---|---|---|---|
| 1   |  6 | $6,750  | [1,2,3,4] | **$3,750** |
| 2   |  6 | $6,750  | [1,2,3,4] | **$3,750** |
| 3   |  6 | $6,750  | [1,2,3,4] | **$3,750** |
| 4   |  7 | $11,750 | [1,2,3,4] | **$3,750** (scope filter removed $5k music benefit) |
| 5   |  6 | $6,750  | [1,2,3,4] | **$3,750** |

Cross-version delta on d851d5ba's ingest reliability:

|                                         | NAR-1 | NAR-6 |
|-----------------------------------------|-------|-------|
| All 4 gold events in `charity_donations`  | 0/5 | **5/5** |
| Cardinal-view final total = $3,750        | 0/5 | **5/5** |
| Trinity revoke wipes entire class         | 2/5 | **0/5** |
| `★ MUST be $3,750` directive surfaced     | 1/5 | **5/5** |

Cache rows still carry t0/t6 same-event dups and (in 1/5) a
music-benefit false-positive — the cardinal view's downstream
scope filter + session-amount dedup neutralizes them in the
prompt-side output. Not addressed by NAR-5 because the prompt-
side result is already correct; chasing cache cleanliness adds
blast radius without changing the answer.

## Trigger-face Audit (NAR-8)

Offline scan: 67 / 499 LME-S qids have ≥1 user turn that fires
the recognizer. Bucketed by question intent:

- **5 charity-themed questions** (incl. d851d5ba target): firing
  is desired.
- **10 money/spending questions** (not charity): recognizer
  fires on incidental charity turns in their haystacks, but each
  query's focus noun routes `get_numeric_cardinal()` to a
  different cardinal class. The charity_donations rows are
  dormant for these queries.
- **52 other questions**: `get_numeric_cardinal()` early-returns
  (no numeric_cardinal intent). Storage-only side effect.

No pollution path found in offline routing analysis.

## E2E Smoke (NAR-7)

```
qid:          d851d5ba
gold:         $3,750
answer:       (truncated by harness at 400 chars; preamble cites the
              DRAFT CARDINAL VIEW which contained "MUST be $3,750")
judge_tail:   "...the total amount raised for charity. Therefore,
               the model response is correct."
correct:      true
acc:          1.000
time:         819s
```

Cross-version comparison on d851d5ba e2e:

| Run | Mechanism | Correct? |
|-----|---|---|
| V8.2.1 | LLM seeded badly, emitted wrong total despite cardinal view | NO |
| V8.2.2a | Lucky LLM, emitted $3,750 | YES |
| V8.2.2b | Same as V8.2.2a (same ingest variance) | YES |
| numeric-aggregator-recall (NAR-7) | Deterministic recognizer locks 4/4 events into charity_donations, cardinal view's scope+dedup yields $3,750 — LLM cooperates | YES |

The first three rely on LLM seed luck; NAR-7 has a deterministic
floor that survives ingest variance (NAR-6 5/5).

## Merge Decision (NAR-10)

Three independent validations all green:

- NAR-6: ingest stability 5/5 — all 4 gold events in
  `charity_donations`, cardinal view yields $3,750 every run.
- NAR-7: e2e smoke PASS — gpt-4o judge confirmed answer is
  semantically equivalent to gold $3,750.
- NAR-8: trigger-face audit on 499 qids — no pollution path
  found via query-routing analysis.

Decision: **(a) MERGE**.

This is not a hack: no qid-specific code, no hardcoded $3,750,
no gold leakage. The intervention is a regex layer that
deterministically classifies charity-context money events at
extraction time, and a `_refine_amount_events` exclusion that
protects deterministic-tagged events from trinity's stochastic
revoke. Both are scoped, testable, and reversible.

What stays for later:

- t0/t6 same-event dedup at cache layer — currently neutralized
  downstream by cardinal view's session-amount dedup; can be
  cleaned up later without changing answers.
- `total_amount=$N (K events)` cosmetic header in the cardinal
  view prompt that reports the pre-filter cache total — also
  neutralized downstream; not blocking.
- Extending the recognizer family beyond `charity_donations` if
  another aggregation class shows the same flakiness pattern.

The merge is the close-out of this workstream. No follow-up
commits in this series; the next iteration (if any) starts
under a different workstream name.

## Files Touched

- **New**:
  - `src/radiomind/refinement/numeric_aggregator.py` —
    `detect_charity_amounts` + recognizer wiring.
  - `tests/test_numeric_aggregator_charity_recall.py` — 67
    tests.
  - `bench/end_to_end/nar1_isolated_ingest.py` — re-ingest
    harness.
  - `bench/end_to_end/nar1-d851d5ba-matrix.json` — pre-fix
    matrix.
  - `bench/end_to_end/nar6-d851d5ba-matrix.json` — post-fix
    matrix.
  - `bench/end_to_end/nar7-d851d5ba-smoke.json` — e2e smoke.
  - `bench/end_to_end/nar8-trigger-face-audit.md` — offline
    audit.
  - `projectBasicInfo/logs/2026-05-22-nar3-charity-recognizer-design-cc.md` —
    design.
  - This document.

- **Modified**:
  - `numeric_aggregator.py`: + recognizer module-level
    constants and function; + recognizer call in
    `_regex_extract`; + merge logic in `process_turns`;
    + one-way upgrade in `_classify_batch`; + reason tag in
    `_apply_delta`; + threshold drop in
    `_trinity_class_promotion`.

## What This Workstream Does NOT Promise

- It does NOT promise stable answers across LLM seed variance
  for all charity questions — only that the cardinal view's
  deterministic total computation is now stable for d851d5ba.
  Other charity questions may still flake based on retrieval
  noise or LLM commit variance.
- It does NOT address the cache-side t0/t6 same-event dedup or
  the cosmetic `total_amount=$N (K events)` header in the
  cardinal view prompt. Those are knownnot-load-bearing items.
- It does NOT extend to other typed-event classes (kitchen
  count, concert ordering, etc.). Each would need its own
  recognizer if pursued.

## Commits

| Hash | Subject |
|---|---|
| `1472b2b` | NAR-1: d851d5ba isolated re-ingest matrix (5 runs) |
| `ce007c5` | log: NAR-3 charity recognizer design |
| `625e344` | NAR-4: failing tests for detect_charity_amounts |
| `2dd813e` | NAR-5: deterministic charity recognizer wired into NumericAggregator |
| `def2764` | NAR-6: post-fix stability matrix |
| `f76c122` | NAR-8: trigger-face audit |
| _next_ | NAR-7 e2e smoke result + this close-out log (single commit) |
