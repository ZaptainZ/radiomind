# SelfAnchor-1b — Helper-Specific Store-Scan Supplement (Close-Out)

**Date**: 2026-05-29
**Author**: Claude Code
**Status**: Implemented + verified. NOT a global retrieval boost.
3-qid e2e smoke 3/3, trigger-face negatives clean, 223 helper
tests pass. No n=100 (per direction).

---

## What shipped

A targeted, read-only store-scan that recovers a single missing
first-person self anchor when a helper has ALREADY entered its
correct semantic channel — never a global `mind.search` change.

`src/radiomind/core/self_anchor.py`:
- `SelfAnchorProof` (kind, value, source_turn_id, quote,
  scan_scope) — every recovery is traceable.
- `scan_current_age_user_turns` — first-person current-age only.
  Production patterns: `I'm N` / `I (just|recently) turned N` /
  `as a N-year-old <occupation>`. NO bare `(\d{2})-year-old`.
  Kin-guard rejects `my dad, as a 58-year-old engineer`. Single
  unambiguous match or refuse.
- `scan_paid_price_user_turns` — item-scoped, reuses SavingsHint
  paid templates, user turns only.

Wired into 3 helpers (only when already triggered + missing
exactly the one self anchor; runner passes mind+domain):
- `savings_arithmetic_hint`: retail present + paid missing → scan paid
- `person_age_average_hint`: `missing == ['self']` only → scan self age
- `maybe_age_interval_commit_closure`: current age missing → scan;
  gate-7 recompute-match still enforced afterward

## Verification

### Unit (`tests/test_self_anchor.py`, 29 cases)

20 unit + 9 integration. Negatives covered: kin-owned age,
"my grandma is 75", bare `N-year-old` w/o occupation,
recommendation age-band, assistant echo, ambiguous two self
ages, single-token item, recompute-mismatch still refuses.

### e2e smoke — 3/3 (the 3 RECOVERABLE qids)

| qid | anchor recovered | answer | correct |
|---|---|---|---|
| `gpt4_d12ceb0e` | self age 32 | "...average age ... is 59.6 years" | ✓ |
| `bb7c3b45` | paid $200 | "You saved $300 on the Jimmy Choo heels." | ✓ |
| `c18a7dc8` | current age 32 (gate-7: 32−25=7) | "7" | ✓ |

All three were anchor-not-in-retrieve refusals before 1b; the
store scan recovered each. (`c18a7dc8`'s initial verdict was a
judge SSL infra error — judge_failed=True — same transient class
as 75f70248; rejudged → PASS. answer="7" == gold.)

### Trigger-face negatives — clean

| qid | trigger | self-age scan | outcome |
|---|---|---|---|
| `157a136e` | age_interval `older` | **None** | kin-guard held: store has grandma 75 + fuzzy "in my 30s", scan did NOT mis-recover. Stays unrecoverable (input limitation). ✓ |
| `6613b389` | age_interval `before` | None | before-mode never reaches age rewrite; scan also returns None. ✓ |
| `e25c3b8d` | SavingsHint | n/a | paid already in retrieve + retail fails same-item proximity → supplement path not reached (SavingsHint-1a behavior preserved). ✓ |

No mis-fire on any trigger-matched but should-not-recover qid.

## Constraints honored (Codex 2026-05-29)

1. ✓ only the 3 recoverable forms (paid / current+self age)
2. ✓ no global `mind.search` change; scan reads store user-turn layer only
3. ✓ helper-specific scope (item phrase for paid; first-person current-age for age)
4. ✓ proof carries source_turn_id + quote + scan_scope in every hint/rewrite
5. ✓ verification order: unit → 3-qid smoke → trigger-face; no n=100
6. ✓ regex limited to first-person/self (Codex regex warning addressed: no bare `(\d{2})-year-old`, kin-guard added)

## Net effect

3 previously-recoverable failures (anchor in store, missed by
retrieve top-200 due to FACT-event dominance, user-turn recall
3-19%) now resolve deterministically without touching retrieval
ranking. Each carries a traceable proof. No regression on
negatives.

## Files

- Module: `src/radiomind/core/self_anchor.py`
- Tests: `tests/test_self_anchor.py` (29)
- Wiring: `arithmetic_hint.py`, `typed_event_hint.py`,
  `age_interval_commit.py`, `run_longmemeval_mem0.py`
- Smoke: `bench/end_to_end/selfanchor-1b-smoke.json` (3/3 post-rejudge)
- Trigger-face: `bench/end_to_end/selfanchor-tface-{157a136e,6613b389}.json`
- Audit script: `bench/end_to_end/selfanchor_trigger_face.py`
- This log; prior: `2026-05-29-selfanchor-1a-audit-cc.md`
