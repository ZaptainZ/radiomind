# Phase2-2c — extract resolve_age_interval_proof + age committer in closure_view

**Date**: 2026-06-01
**Author**: Claude Code
**Status**: Done. Extracted `resolve_age_interval_proof(...) -> ProofResult |
None` from `maybe_age_interval_commit_closure` (byte-identical, guarded by the
age exact-output suite) and used it to add the **age committer** to
`diagnose_qid.py`'s `closure_view`. Both committers (cashback, age) now have a
proof view. No runner behaviour change, no dispatcher, no benchmark.

---

## Part 1 — resolver extraction (src/radiomind/core/age_interval_commit.py)
- New `resolve_age_interval_proof(question, retrieved_memories,
  temporal_section, mind=None, domain=None)`: the **answer-independent** half
  of the closure — gates 1-6 (skill_name / conf>=0.85 / int-parse / non-neg /
  mode older|younger / past-age found / current-age found incl. store-scan) +
  `age_interval_proof_to_result(...)`. Returns `None` on any structural gate
  failure. Gate 7 (recompute) is NOT enforced here — it is carried on the
  ProofResult as `recompute_ok` and enforced by `commit_on_abstain`; gate 8
  (pure abstain) is the caller's commit decision.
- `maybe_age_interval_commit_closure` body reduced to the cashback-shaped
  delegation:
  ```
  if not is_commit_abstain_candidate(llm_answer): return llm_answer
  proof = resolve_age_interval_proof(question, retrieved_memories,
                                     temporal_section, mind=mind, domain=domain)
  return commit_on_abstain(proof, llm_answer)
  ```
- **Byte-identity argument**: every original bypass returns `llm_answer`
  and so does the new path —
  - concrete answer → fast-bypass (was gate 8, now first);
  - wrong/low skill / bad mode / missing evidence → resolver `None` →
    `commit_on_abstain(None)` → `llm_answer`;
  - recompute mismatch → proof built with `recompute_ok=False` →
    `commit_on_abstain` rejects → `llm_answer` (matches the old gate-7 return);
  - all gates pass → same `rendered`.
  The 34 age exact-output tests (incl. `test_skip_when_recompute_does_not_
  match_skill` and the canonical rewrite) confirm it.

## Part 2 — age committer in closure_view (bench/end_to_end/diagnose_qid.py)
- `_probe_closure_view(...)` gained a `temporal_section: str = ""` param and an
  `age_interval` committer branch (calls `resolve_age_interval_proof` →
  same projection shape as cashback: proof fields incl. `confidence`, plus
  `would_commit_on_canonical_abstain` / `would_overwrite_concrete_answer`).
- Call site passes `helper_signals.get("run_temporal_precision", "")` as the
  temporal section (the STRUCTURED SKILL string the runner injects).

## Verification
- Age + committer + carrier + self_anchor suite → **105 passed** (unchanged →
  byte-identical resolver extraction).
- `diagnose_qid.py` syntax OK; unit smoke of `_probe_closure_view` on a real-
  shaped age case (graduated at 25, now 32, skill=7):
  `age_interval.proof_available=true`, `value=7`, **dual `sources`** (at_age +
  current_age, each with quote), `recompute_ok=true`, `confidence=0.9`,
  `would_commit_on_canonical_abstain=true`, `would_overwrite_concrete_answer=false`;
  cashback `no proof`; suppressors `detected=no / bypass=true`. All correct.
- No ingest-type `diagnose_qid --qid …` run (keeps it a light diagnostic UX
  change, per scope). The unit smokes exercise the real resolver + gate.

## Files
- `src/radiomind/core/age_interval_commit.py` (resolver + closure refactor)
- `bench/end_to_end/diagnose_qid.py` (age committer + temporal_section param)

## State / next
Both committers (cashback, age) now expose a `ProofResult`/commit-gate view in
diagnose; suppressors (role, TESG) have what-if verdicts. `closure_view` is
feature-complete for the current closure set. Optional later: full
`diagnose_qid --qid 9aaed6a3` / suppressor-qid integration runs (need ingest +
LLM); no further extraction warranted (savings/person_age stay hint-only).
