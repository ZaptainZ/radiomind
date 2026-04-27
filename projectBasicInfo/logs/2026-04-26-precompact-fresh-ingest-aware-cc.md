# PreCompact hook: fresh-ingest aware seatbelt

**Date**: 2026-04-26
**Author**: cc
**Type**: bug fix / UX

## Background

User invoked `/compact` and saw "Compaction blocked by PreCompact hook" with the SAVE_PROMPT splash. They asked to "fix this issue blocking compaction".

History:
- `552b4b9`: hook always blocked → users disabled it
- `35c9f77`: check `MAX(memories.created_at)` within 120s → approve. But the 120s window was too tight for "ingest, think 30 min, then /compact" workflows.
- `6def67b`: stateful ladder + 30 min fresh window. Punished "no recent ingest" callers with a block-loop.
- `b529f81`: pure cooldown seatbelt (block first attempt, approve retry within 10 min). But the user *always* sees a scary block on the first /compact, even when the stop_hook just ingested seconds ago.

The core mismatch: stop_hook auto-ingests every ~15 messages, so on most active sessions the data is *already saved* when the user compacts — the seatbelt block is gratuitous.

## Goal

`/compact` should pass through silently when memories were recently saved. Fall back to a one-shot reminder only when the data really is stale.

## Approach

Two-stage decision in `src/radiomind/hooks/precompact_hook.py`:

1. **Fresh-ingest gate (new)**: `SELECT MAX(created_at) FROM memories`. If within `RADIOMIND_COMPACT_FRESH_S` (default 1800s = 30 min) → approve. No state touched.
2. **Cooldown seatbelt (kept from b529f81)**: if `last_blocked_ts` within `RADIOMIND_COMPACT_COOLDOWN_S` (default 600s) → approve and clear state.
3. **Otherwise**: block once with `SAVE_PROMPT`, seed `last_blocked_ts`.

Errors anywhere → fall through to approve (hook must never wedge the user).

DB opened read-only (`mode=ro`) with 1s timeout, so a busy daemon write doesn't make the hook block on a SQLite lock.

## Modified files

- `src/radiomind/hooks/precompact_hook.py` — rewrite
- `tests/test_precompact_hook.py` — 10 tests (was 5):
  - `test_fresh_ingest_approves` — happy path
  - `test_no_db_falls_through_to_seatbelt`
  - `test_empty_db_falls_through_to_seatbelt`
  - `test_stale_ingest_falls_through_to_seatbelt`
  - `test_retry_within_cooldown_approves_and_clears`
  - `test_retry_after_cooldown_blocks_again`
  - `test_corrupt_state_falls_through_to_block`
  - `test_env_override_short_cooldown`
  - `test_env_override_short_fresh_window`
  - `test_fresh_ingest_overrides_stale_cooldown`

`hooks/scripts/precompact_save.py` is a delegator and inherits the new behavior automatically.

## Verification

- `pytest tests/test_precompact_hook.py` → 10 passed.
- Real-state sanity check: db last_ingest 16h ago, last_blocked_ts 6 min ago → hook approves (cooldown path). Matches expected UX.
- Legacy delegator (`hooks/scripts/precompact_save.py`) on a fresh `/tmp` home produces a `block` decision — seatbelt path engaged for fresh-install with no data.

## Conclusion

`/compact` now passes silently in the common case (active session). The reminder only fires when memories really are stale — seatbelt, not wall.

Knobs: `RADIOMIND_COMPACT_FRESH_S` (default 1800), `RADIOMIND_COMPACT_COOLDOWN_S` (default 600).
