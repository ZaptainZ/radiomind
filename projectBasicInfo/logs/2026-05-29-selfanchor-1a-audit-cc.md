# SelfAnchor-1a — Self-Statement Anchor Recall Audit (Read-Only)

**Date**: 2026-05-29
**Author**: Claude Code
**Status**: Read-only audit complete. No helper / search change.
Identifies which self-anchor refusals are retrieve-recall-
recoverable vs other shapes, before designing SelfAnchor-1b.

---

## Why

Phase 1.5 instrumentation surfaced that 3 helper failures share
a refusal where the needed first-person self-statement anchor
(paid price / current age) is present in the haystack but ranks
outside retrieve top-200. SelfAnchor-1a verifies that claim
rigorously before any code touches the retrieval / store-scan
path.

## Cohort selection (trigger pre-screen, full LME-S 500)

Reused each helper's actual trigger regex. Qids that could
produce a self-anchor refusal:

- SavingsHint (`how much did I save on [item]`): `bb7c3b45`,
  `e25c3b8d`
- age_interval (`how many years older/younger ...`): `c18a7dc8`,
  `157a136e`, `6613b389`
- person_age (avg age of me+parents+grandparents): `gpt4_d12ceb0e`

Union cohort = 6 qids. Tight surface (no global blast radius).

## Stage 1 — raw-haystack ground truth

Scanned RAW user turns (dataset read, no ingest) for the needed
anchor with strict first-person regexes:

| qid | needed anchor | found in raw user turn? | strict regex recoverable |
|---|---|---|---|
| bb7c3b45 | paid price | ✓ `$200` (answer_de64539a_1_t0) | ✓ |
| e25c3b8d | paid price | ✓ `$200` (answer_6702277b_2_t6) | ✓ |
| c18a7dc8 | current age | ✓ `32` ("As a 32-year-old", answer_2e2085fa_2_t8) | ✓ |
| gpt4_d12ceb0e | self current age | ✓ `32` ("I just turned 32", answer_2504635e_1_t0) | ✓ |
| `157a136e` | current age | ✗ **0 hits** | — |
| `6613b389` | (not age — before-mode event interval) | n/a | — |

Two exclusions:

- **157a136e** — gold=43 needs user age 32, but the haystack
  only has fuzzy "I'm in my 30s" (no exact value). This is an
  **input limitation** (consistent with the prior TSI-1d
  finding), NOT a recall gap.
- **6613b389** — "how many months before my anniversary did
  Rachel get engaged" trips the age_interval trigger but needs
  an **event-date interval**, not a current-age anchor.
  Mis-classified into the cohort by the trigger; not a
  self-anchor case.

## Stage 2 — store-vs-retrieve matrix

For the 4 qids with a real anchor, ingested into a per-qid
sandbox and compared anchor presence across raw / store /
retrieve(top-200), plus user-turn recall:

| qid | anchor | in_raw | in_store | in_retrieve | user-turn recall (retr/store) | verdict |
|---|---|---|---|---|---|---|
| `bb7c3b45` | paid $200 | ✓ | ✓ | ✗ | 46/247 = 18.6% | **RECOVERABLE** |
| `c18a7dc8` | age 32 | ✓ | ✓ | ✗ | 10/252 = 4.0% | **RECOVERABLE** |
| `gpt4_d12ceb0e` | self age 32 | ✓ | ✓ | ✗ | 7/236 = 3.0% | **RECOVERABLE** |
| `e25c3b8d` | paid $200 | ✓ | ✓ | ✓ | 19/260 = 7.3% | helper-side (not recall) |

## Findings

1. **The mechanism is confirmed**: FACT-layer events dominate
   retrieve top-200, so raw user turns are squeezed to a tiny
   fraction (3–19%). The user's first-person self-statement
   (paid price / current age) lives in a user turn that ranks
   out of the window even though it's in the store.

2. **3 RECOVERABLE cases** (`bb7c3b45`, `c18a7dc8`,
   `gpt4_d12ceb0e`): the anchor IS in the store's user-turn
   layer; a helper-specific store-scan would recover it. These
   are the precise SelfAnchor-1b targets.

3. **e25c3b8d is NOT a recall case**: its paid $200 IS in
   retrieve. SavingsHint refused it for a different reason —
   the retail $500 anchor fails the same-item 80-char
   proximity gate (documented in SavingsHint-1a as correct
   conservative behavior). Out of SelfAnchor scope.

4. **157a136e / 6613b389 excluded** (input limitation /
   mis-trigger). No code can recover an anchor that isn't in
   the data.

## Risk assessment (for SelfAnchor-1b)

| risk | assessment |
|---|---|
| store-scan surfaces assistant echo instead of user statement | LOW — scan restricted to role=user / `[user]` prefixed entries only |
| store-scan surfaces an unrelated self-statement | LOW for these 3 — each anchor value is unique in its store (single `$200` / single `32`); but 1b must still scope to the helper's own anchor (item phrase for paid, first-person current-age regex for age) |
| store-scan reintroduces the misattribution risk JAB/cashback just fixed | MEDIUM — mitigated by requiring the helper to be ALREADY triggered and missing ONLY this one anchor; scan does not invent triggers |
| proof traceability | REQUIRED — 1b must return source turn_id + quote into the proof, same contract as cashback merchant scoping |

## SelfAnchor-1b scope recommendation (NOT yet implemented)

Targeted, helper-specific store-scan supplement — only when the
helper has already fired its trigger and is missing exactly one
self anchor:

- **SavingsHint**: when retail anchor is satisfied but paid
  anchor is missing from retrieved user turns, scan the
  domain store's user turns for the paid price near the query
  item phrase. (bb7c3b45)
- **age_interval / person_age**: when the event/kin side is
  satisfied but the user's current age is missing, scan the
  store's user turns for a first-person current-age statement
  (`I'm N` / `I just turned N` / `as a N-year-old`). (c18a7dc8,
  gpt4_d12ceb0e)

Constraints (carried from prior cycles):
- user turns only, never assistant echo
- helper-specific anchor scope (no generic boost)
- must emit source turn_id + quote into proof
- only activate when helper already triggered + single anchor
  missing
- target smoke on the 3 RECOVERABLE qids + trigger-face audit;
  NO n=100

## Files

- Audit script: `bench/end_to_end/selfanchor_1a_audit.py`
- Per-qid results: `bench/end_to_end/selfanchor-1a-{bb7c3b45,e25c3b8d,c18a7dc8,gpt4_d12ceb0e}.json`
- This log: `projectBasicInfo/logs/2026-05-29-selfanchor-1a-audit-cc.md`
- Related: `projectBasicInfo/logs/2026-05-28-core-skill-arch-diagnostic-ux-design-cc.md` (Phase 1.5 + 1.5a)
