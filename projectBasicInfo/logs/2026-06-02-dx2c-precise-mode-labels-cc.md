# DX-2c: precise failure-mode labels (diagnostic-only)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Implemented + tested (20 path_summary tests, regression pack 16/16
ALL PASS) + verified on the two real probe artifacts. Awaiting review before
commit. **Diagnostic-only: no retrieval/answer/runner behavior changed.**

---

## Goal
The c18a7dc8 + bb7c3b45 probes surfaced two distinct Family-C failure modes that
the existing labels lumped together. DX-2c makes them show up directly in
`diagnosis.layer`, so future triage names the mode without re-deriving it. No
business path touched — only the classification in `build_path_summary`.

## Two new labels

### `concrete_wrong_bypassed_committer` (DX-2c, e2e overlay)
`_overlay_e2e` now also takes `closure_decision`. When the e2e answer is WRONG,
not an infra/judge error, **not a pure abstain**, AND a committer was ready
(`proof_available && would_commit_on_abstain`), the label is
`concrete_wrong_bypassed_committer`: the committer's `commit_on_abstain` never
fires because the answer-LLM returned a concrete wrong value, not an abstain
(its polarity only rescues abstains). The abstain trust-gap (committer ready +
answer IS an abstain) still maps to `answer_or_judge_path`.
- = the **c18a7dc8** mode (live answer "You are 0 years older…", gold 7).

### `proof_input_turn_missing` (DX-2c, deterministic)
`_classify_layer`'s refused branch now checks the refusal reason: if it contains
`not_found` / `not_in_retrieved` / `not_in_user_turns`, the required proof input
was not found *in the retrieved turns* (the evidence turn was likely out-ranked /
not retrieved — a retrieval problem, not an extraction bug) → label
`proof_input_turn_missing`. A plain gate miss (`no_trigger_match`,
`skill_did_not_fire`, `no_cashback_rate_in_memories`) stays `helper_refusal`.
This also picks the missing-input refusal over a generic one, de-noising the
old `refused[0]` bias toward irrelevant helpers.
- = the **bb7c3b45** mode (savings `paid_anchor_not_found_in_user_turns`; the
  $200 paid turn was never retrieved).

## Verification
- `tests/test_path_summary.py` +5 (now 20): bypass label; committer-ready +
  abstain stays trust-gap; proof_input_turn_missing label; missing-input
  preferred over generic; generic stays helper_refusal. All earlier DX-2a/2b
  tests still pass (the abstain trust-gap case is unchanged).
- Real-artifact sanity (offline, no ingest):
  - c18a7dc8 current-build rec + fresh run ("0") → `concrete_wrong_bypassed_committer`.
  - bb7c3b45 current-build rec → `proof_input_turn_missing`.
- Regression pack: **16 categories ALL PASS** (`diagnostic:path-summary` 20).

## Scope / boundary
- Pure projection over existing diagnose sections. No retrieval ranking change,
  no answer/judge change, no new helper/closure, no runner change.
- Already-committed `diagnose-*-dx2b.json` artifacts keep their pre-DX-2c baked
  `path_summary` labels; re-running diagnose would relabel them. Not regenerated.
- The "quantitative-turn retrieval weighting" idea (bb7c3b45's real fix) is
  explicitly NOT implemented — recorded as a future **read-only cohort audit**
  (how many LME-S fails share "gold session hit but the number-bearing turn
  out-ranked out of top-k") before any high-blast-radius ranking change.

## Files
- `bench/end_to_end/diagnose_qid.py` (`_classify_layer`, `_overlay_e2e` +
  closure arg, call site)
- `tests/test_path_summary.py` (+5)
