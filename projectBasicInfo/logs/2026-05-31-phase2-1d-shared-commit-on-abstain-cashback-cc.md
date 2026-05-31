# Phase2-1d — shared `commit_on_abstain`, cashback migrated (one closure)

**Date**: 2026-05-31
**Author**: Claude Code
**Status**: Done. Adds the shared `commit_on_abstain(proof, llm_answer)`
gate and migrates **only the cashback** closure tail onto it. age left on
its own tail (deliberately — migrate one at a time to isolate any byte-path
diff). role / TESG / runner untouched. Byte-identical (full suite green).

---

## Scope (narrow, as agreed)
- One shared gate; migrate **one** committer (cashback). age is 1e.

## Changes
- `src/radiomind/core/proof_result.py`: added
  `commit_on_abstain(proof: ProofResult | None, llm_answer) -> str`:
  commit `proof.rendered` ONLY when `_is_pure_abstain(llm_answer)` AND
  `proof is not None` AND `proof.recompute_ok`; else return `llm_answer`.
  (`_is_pure_abstain` imported lazily from age_interval_commit — the
  canonical detector both committers already used.)
- `src/radiomind/core/arithmetic_hint.py`: `maybe_cashback_commit_closure`
  tail replaced with
  ```
  proof = resolve_cashback_proof(...)
  result = cashback_proof_to_result(proof) if proof is not None else None
  return commit_on_abstain(result, llm_answer)
  ```
  The inline abstain-check / None-check / recompute-check / f-string are
  gone — all now live in the shared gate + the 1b adapter's `rendered`.
- `tests/test_commit_on_abstain.py` (new, 4 tests): the gate's own contract
  (commit on abstain+valid proof; never overwrite concrete incl. hybrid;
  None proof unchanged; recompute-fail unchanged).

### One intentional behavior delta (no output effect)
`resolve_cashback_proof` now runs unconditionally (even when the LLM gave a
concrete answer), because the abstain check moved into `commit_on_abstain`
*after* resolve. It is read-only and its result is discarded on the concrete
path, so **committed bytes are identical**. The 15 exact-output cashback
closure tests (incl. concrete-preserved / wrong-concrete-preserved) passing
is the proof.

## Verification
- cashback closure + field + cashback adapter + age closure + age adapter +
  self_anchor → **100 passed** (same count as the pre-migration baseline →
  byte-identical). Plus `test_commit_on_abstain.py` (4) green.
- grep confirms the cashback closure no longer references `_is_pure_abstain`
  directly — the gate is centralized.
- No change to age_interval_commit.py / role_mismatch_guard /
  temporal_endpoint_guard / run_longmemeval_mem0.py.

## Iteration note
First migration Edit silently failed (my `old_string` used a multi-line
`return (...)` format but the file had the compact `return (f"…" f"…")` with
a leading blank line). The mismatch left the closure unmigrated while
`commit_on_abstain` was already added — the suite still showed "100 passed"
because the OLD inline closure was intact. Re-applied with the exact text;
grep + the centralized-gate check confirm it took.

## Next (Phase2-1e, optional)
Migrate **age** tail onto `commit_on_abstain` the same way
(`age_interval_proof_to_result(...)` already returns a `ProofResult`; the
closure would resolve its proof, build the carrier, and
`return commit_on_abstain(result, llm_answer)`). Gate on the age/TSI suite
staying byte-identical. After that both committers share one gate and the
two adapters; suppressors (role, TESG) remain a separate family, never in
the proof registry. No dispatcher.
