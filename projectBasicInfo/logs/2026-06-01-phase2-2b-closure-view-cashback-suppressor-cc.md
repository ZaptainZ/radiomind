# Phase2-2b — diagnose_qid `closure_view` (cashback committer + suppressor what-if)

**Date**: 2026-06-01
**Author**: Claude Code
**Status**: Implemented (cashback proof view + role/TESG suppressor what-if).
Read-only diagnostic projection only — no runner change, no dispatcher, no
new helper family, no benchmark. age committer view deferred (per the
2026-06-01 audit) until a shared age proof resolver is extracted.

---

## Scope (from the 2026-06-01 diagnostic-ux audit)
Add a `closure_view` section to `bench/end_to_end/diagnose_qid.py` answering
"would a closure rewrite the LLM answer for this qid?", preserving the
two-family polarity split:
- **committers** (commit-on-abstain): cashback only this slice.
- **suppressors** (downgrade-overcommit): role + temporal endpoint.

## Changes (bench/end_to_end/diagnose_qid.py only)
- `_probe_closure_view(question, mem_results, mind, domain) -> dict`:
  - cashback: `resolve_cashback_proof` → `cashback_proof_to_result` →
    emits `proof_available`, the full `ProofResult` projection (kind/value/
    inputs/sources/recompute_ok/subject/scan_scope/rendered), and two
    what-ifs via the shared gate: `would_commit_on_canonical_abstain`
    (`commit_on_abstain(pr, ABSTAIN) == pr.rendered`) and
    `would_overwrite_concrete_answer`
    (`commit_on_abstain(pr, "$1.23 …") != "$1.23 …"` → always False; proves
    the never-overwrite-concrete invariant).
  - role / temporal: `detect_*` detection dict + what-ifs against
    deterministic sample answers — `would_suppress_sample_overcommit`
    ("You manage a team of 12 engineers." / "You worked there for 5 years.")
    and `would_bypass_canonical_abstain`, plus `rendered_if_suppressed`.
  - every branch wrapped in try/except → the probe never crashes diagnose.
- `_print_closure_view(cv)`: compact human summary.
- Wiring: `closure_view = _safe(_probe_closure_view, …)` after the
  self-anchor probe; `"closure_view"` added to the `rec` JSON; printed after
  `_print_summary`.

Signatures confirmed before calling: `detect_role_mismatch(q, mems)` /
`maybe_rewrite_with_guard(q, mems, ans)` (no mind/domain);
`detect_temporal_endpoint_mismatch(q, mems, mind, domain)` /
`maybe_rewrite_with_temporal_guard(q, mems, ans, mind, domain)`.

## Verification
- `SYNTAX_OK`.
- Unit smoke of `_probe_closure_view` on synthetic 9aaed6a3-shaped cashback
  mems (no ingest needed — calls the real builders/gates):
  - cashback: `proof_available=true`, `value=0.75`,
    `rendered="You earned $0.75 in cashback at SaveMart."`,
    `would_commit_on_canonical_abstain=true`,
    `would_overwrite_concrete_answer=false`.
  - role / temporal: `detected=no`, `suppress_overcommit=false`,
    `bypass_abstain=true` (correct — neither fires on a cashback question and
    both pass an abstain through).
  This exercises the actual proof resolution + shared gate + suppressor
  detection/rewrite paths.

## Not done (deferred, by design)
- **age committer view**: needs a shared `resolve_age_interval_proof(...) ->
  ProofResult | None` extracted from `maybe_age_interval_commit_closure`
  first (the audit warns hand-reconstructing age's 8 gates in diagnose would
  duplicate the production sequence). That is a code-change slice guarded by
  the age exact-output tests — a separate step.
- **Full integration runs** (`diagnose_qid.py --qid 9aaed6a3` for cashback;
  `031748ae_abs` / `gpt4_93159ced_abs` / NovaTech-negative for suppressors)
  require a sandbox ingest (~47 sessions) + LLM calls. Not run here to honour
  the "no benchmark" scope; the unit smoke already validates the projection
  logic. These single-qid diagnose runs are the recommended next check when
  desired.
- savings / person_age NOT added to `committers` (hint-only; no commit
  closure today).

## Files
- `bench/end_to_end/diagnose_qid.py` (only).
