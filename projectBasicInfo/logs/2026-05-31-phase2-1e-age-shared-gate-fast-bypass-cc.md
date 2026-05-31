# Phase2-1e — age migrated to shared gate + fast-bypass helper

**Date**: 2026-05-31
**Author**: Claude Code
**Status**: Done. Both committer closures (cashback, age) now share
`commit_on_abstain`. Added `is_commit_abstain_candidate` so each closure
fast-bypasses a concrete answer BEFORE resolving its proof — fixing the
1d cost regression (cashback resolving on the concrete path). Byte-identical
(full suite green). role / TESG / runner untouched; no dispatcher.

---

## Design fix carried in (from 1d review)
1d moved cashback's abstain check *after* `resolve_cashback_proof`, so a
concrete answer paid an unnecessary resolve (incl. possible store-scan).
1e exposes a cheap pre-check both committers call before resolving.

## Changes
- `src/radiomind/core/proof_result.py`:
  - Added `is_commit_abstain_candidate(llm_answer) -> bool` (wraps the
    canonical `_is_pure_abstain`).
  - `commit_on_abstain` now calls it (single definition of the abstain check).
- `src/radiomind/core/arithmetic_hint.py` (cashback): fast-bypass restored —
  `if not is_commit_abstain_candidate(llm_answer): return llm_answer` BEFORE
  `resolve_cashback_proof`. Concrete answers no longer resolve/store-scan.
- `src/radiomind/core/age_interval_commit.py` (age): final commit now routes
  through the shared gate —
  `result = age_interval_proof_to_result(...); return commit_on_abstain(result, llm_answer)`.
  age's gates 1–8 (incl. gate 8 pure-abstain BEFORE evidence finding, and
  gate 7 recompute) are kept as fast pre-checks; at the commit point abstain
  and recompute_ok already hold, so `commit_on_abstain` returns the rendered
  bytes unchanged. (age already fast-bypassed via gate 8 — no cost regression
  there; this step is the gate-sharing.)
- `tests/test_commit_on_abstain.py`: +1 test for `is_commit_abstain_candidate`.

## Verification
- test_commit_on_abstain + cashback closure/field/adapter + age
  closure/adapter + self_anchor → **105 passed** (104-test 1d baseline
  plus the new `is_commit_abstain_candidate` unit test). The exact-output
  cashback + age tests passing is the proof both migrations changed no
  committed byte.
- syntax + imports clean for all three modules.
- No change to role_mismatch_guard / temporal_endpoint_guard /
  run_longmemeval_mem0.py.

## End state of the committer family
Both committers now:
- fast-bypass concrete answers via `is_commit_abstain_candidate` before any
  proof resolution,
- build a `ProofResult` via their adapter (`cashback_proof_to_result` /
  `age_interval_proof_to_result`),
- commit via the single shared `commit_on_abstain` gate.
Each closure keeps its own domain-specific proof resolution + pre-gates. The
suppressor family (role, TESG) remains entirely outside the proof registry
(opposite abstain polarity, no value/recompute — 1a §3). There is still NO
dispatcher: the runner calls each closure directly, in order.

## Next (optional)
The Phase-2 carrier + shared gate are complete for both committers. A further
step could fold the savings/person_age *hints* into the same carrier IF they
ever gain a commit-on-abstain closure (none today — they are hint-only). Not
warranted now. The registry/dispatcher idea from the original Phase-2 sketch
is intentionally NOT built: the audit (1a) showed it would over-abstract two
genuinely different families. Recommend stopping the abstraction here.
