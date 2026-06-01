# Diagnostic UX Phase 2 — Proof-Aware View Audit

**Date**: 2026-06-01
**Author**: Codex
**Status**: Read-only audit complete. No code changes in this step.

---

## Goal

Design the next `diagnose_qid.py` upgrade after Phase 2 proof carrier work:
show not just helper strings/refusal reasons, but the proof and commit/suppress
decision state that determines final answer rewriting.

This is intentionally a 1a-style audit before implementation.

## Current State

`bench/end_to_end/diagnose_qid.py` already provides:

- retrieve top-200 / top-30 visibility
- helper signals
- structured `diagnose_*` refusal reasons for savings, cashback, person_age,
  and age_interval
- SelfAnchor store-scan probes for paid/current-age/cashback-rate anchors
- FACT-layer anchor probes
- JAB what-if for canonical abstain

This is useful, but it still lacks a direct "would this closure rewrite the
LLM answer?" view.

## Phase 2 Finding Reused Here

There are two opposite closure families:

| family | members | acts when | effect | proof value? |
|---|---|---|---|---|
| COMMIT_ON_ABSTAIN | cashback, age_interval | answer is pure abstain | commits deterministic value | yes |
| SUPPRESS_OVERCOMMIT | role, temporal endpoint | answer is concrete overcommit | downgrades to abstain | no |

Diagnostic UX must preserve this polarity split. A single generic
`commit_closure` view would hide the key safety invariant.

## What Fields Are Already Available

### COMMIT_ON_ABSTAIN

Cashback:

- `resolve_cashback_proof(...)` builds the proof dict.
- `cashback_proof_to_result(...)` converts it to `ProofResult`.
- `commit_on_abstain(proof, llm_answer)` is the shared gate.
- `diagnose_cashback(...)` surfaces `fired`, `refusal_reason`, `merchant`,
  `amount`, `rate`, and computed cashback, but does **not** yet expose a
  `ProofResult`/commit-gate view.

Age interval:

- `age_interval_proof_to_result(...)` builds `ProofResult`.
- `maybe_age_interval_commit_closure(...)` has domain gates before building the
  proof.
- `diagnose_age_interval(...)` surfaces skill/confidence/current-age/past-age
  failure state, but also does **not** yet expose a `ProofResult`/commit-gate
  view.

### SUPPRESS_OVERCOMMIT

Role:

- `detect_role_mismatch(...)` returns the detection dict.
- `_looks_over_committed(answer)` decides whether to rewrite a concrete answer.
- `maybe_rewrite_with_guard(...)` renders the final suppressor answer.
- `diagnose_qid.py` currently only shows the prompt guard string, not the
  post-rewrite verdict.

Temporal endpoint:

- `detect_temporal_endpoint_mismatch(...)` returns employer, evidence support,
  and explicit-negative/future-plan state.
- `_looks_over_committed(answer)` decides whether to rewrite concrete duration.
- `maybe_rewrite_with_temporal_guard(...)` renders the final suppressor answer.
- `diagnose_qid.py` currently only shows the prompt guard string, not the
  suppressor verdict.

## Proposed Phase2-2b Shape

Add a read-only `closure_view` section to `diagnose_qid.py`:

```json
{
  "closure_view": {
    "committers": {
      "cashback": {
        "proof_available": true,
        "proof": { "kind": "cashback", "value": 0.75, "inputs": "...",
                   "sources": "...", "recompute_ok": true,
                   "rendered": "You earned $0.75 in cashback at SaveMart." },
        "would_commit_on_canonical_abstain": true,
        "would_overwrite_concrete_answer": false
      },
      "age_interval": { "...": "same shape" }
    },
    "suppressors": {
      "role": {
        "detection": "... or null",
        "would_suppress_sample_overcommit": true,
        "would_bypass_canonical_abstain": true,
        "rendered_if_suppressed": "The information provided is not enough..."
      },
      "temporal_endpoint": { "...": "same shape" }
    }
  }
}
```

Important: this is a diagnostic projection only. It should not introduce a
runtime dispatcher or move runner ordering.

## Implementation Notes for 2b

1. Import and call committer proof builders directly:
   - `resolve_cashback_proof`
   - `cashback_proof_to_result`
   - `age_interval_proof_to_result` only if age gates can be reconstructed
     safely from `diagnose_age_interval` / temporal section data.

2. For age, do not duplicate all gate logic by hand unless necessary. Safer
   option: add a small pure resolver in `age_interval_commit.py` that returns
   `ProofResult | None`, then have both closure and diagnose call it. That is a
   code-change step and should be guarded by the existing age exact-output tests.

3. For suppressors, add diagnostic verdicts next to current prompt guards:
   - detection present?
   - sample overcommit would be suppressed?
   - canonical abstain would bypass?
   - concrete existing answer is not available in `diagnose_qid.py`, so use
     deterministic sample strings for "what-if" unless a saved answer is passed
     in a future flag.

4. Keep `refusal_reason` in diagnose output, not in live `ProofResult`.

5. Do not include savings/person_age in `committers` yet. They are hint-only
   today; no observed commit-closure evidence.

## Recommended Order

Phase2-2b should be implemented in two small steps:

1. **Cashback-only commit proof view**
   - simplest because `resolve_cashback_proof` and
     `cashback_proof_to_result` already exist.
   - add JSON view + human summary.
   - test on `9aaed6a3`.

2. **Suppressor what-if view**
   - role + TESG detection and sample overcommit/bypass verdicts.
   - test on `031748ae_abs`, `gpt4_93159ced_abs`, and the NovaTech negative.

Age proof view should follow only after deciding whether to extract a shared
age proof resolver; otherwise the diagnose code risks duplicating the exact
gate sequence from the production closure.

## Decision

Proceed to implementation only as a diagnostic UX change:

- no runner behavior change
- no registry/dispatcher
- no new helper family
- no benchmark run required

The correct next implementation slice is **Phase2-2b: cashback proof view +
suppressor what-if view**. Age proof view is a later slice after a resolver
extraction audit.
