# TrustClosure-1a — Trust-Gap Audit (Read-Only)

**Date**: 2026-05-30
**Author**: Claude Code
**Status**: Read-only. Confirms cashback is the only currently
unhandled helper with an EMPIRICAL trust-gap. age_interval already
has a commit-closure (TSI-1d) — the validated precedent
TrustClosure-1b generalizes. savings/person_age not observed
abstaining (6/6 commit). No code change here.

---

## Method

Added a uniform read-only telemetry field
`record["helper_hints"]` to the runner:
`{ savings, person_age, cashback, role_guard, temporal_endpoint }`
= which deterministic hint helpers fired, plus
`answer_pure_abstain` (JAB-1b `is_abstain_response` on the final
answer). The **trust-gap signature** is `hint_emitted=True AND
answer_pure_abstain=True` — the LLM was handed a correct
deterministic hint and abstained anyway.

Ran the 3 hint-helper representative qids × 3 each:
- savings → `bb7c3b45`
- person_age → `gpt4_d12ceb0e`
- cashback → `9aaed6a3`

## Results

| helper | qid | r1 | r2 | r3 | trust-gap |
|---|---|---|---|---|---|
| savings | bb7c3b45 | fired, commit | fired, commit | fired, commit | **0/3** |
| person_age | gpt4_d12ceb0e | fired, commit | fired, commit | fired, commit | **0/3** |
| cashback | 9aaed6a3 | fired, commit | **fired, ABSTAIN** | fired, commit | **1/3** |

Combined with the SelfAnchor-2b telemetry (run7-11: 9aaed6a3
4/5 commit, 1 trust-gap), cashback's trust-gap rate is ~1/4–1/3.

## Findings

1. **Cashback is the only helper with an empirical trust-gap**
   in this audit. `9aaed6a3` abstains a fraction of the time even
   when the hint carries the full `1% × $75 = $0.75`.

2. **savings / person_age were not observed abstaining** (6/6
   commit). This does NOT prove they never trust-gap — they are
   hint-only and structurally just as vulnerable; this is a small
   sample and the LLM happened to commit every time. They are out
   of the 1b pilot scope only because there is no evidence to act
   on yet.

3. **age_interval already has a commit-closure**: TSI-1d
   (`maybe_age_interval_commit_closure`). The age trust-gap was
   discovered in the JAB-1a cycle (skill computed 7, LLM
   abstained) and is already handled by a post-rewrite gated on
   recompute-match + pure-abstain. **This is the validated
   precedent.** TrustClosure-1b is not a new mechanism — it
   generalizes the TSI-1d pattern to cashback.

   Closure family so far:
   - role mismatch → `maybe_rewrite_with_guard` (V8.2.2b)
   - temporal endpoint → `maybe_rewrite_with_temporal_guard` (TESG-1c)
   - age_interval → `maybe_age_interval_commit_closure` (TSI-1d)
   - **cashback → (proposed TrustClosure-1b)**

## Why cashback trust-gaps more than savings/person_age (hypothesis)

Not investigated deeply; a plausible factor is that the cashback
answer is a small sub-dollar value ($0.75) that reads as
"uncertain / not enough info" to the LLM, whereas $300 and 59.6
are larger and read as confident facts. Also 9aaed6a3 is the
only cashback qid (trigger surface 1), so any flakiness is
concentrated. This is a hypothesis, not a basis for the fix.

## TrustClosure-1b scope (pilot = cashback)

Generalize the TSI-1d closure contract to cashback. Hard gate
(Codex-locked, mirrors TSI-1d):
- cashback helper has a complete deterministic proof:
  merchant-scoped rate (retrieve or SelfAnchor-2b store-scan,
  with source_turn_id) × retrieved spend amount → product
- the rate is single, merchant-scoped, no competing-merchant
  mismatch (reuse `_find_cashback_rate_scoped`)
- LLM final answer is a PURE canonical abstain (JAB-1b
  `is_abstain_response`, no concrete commitment elsewhere)
- recompute check: rate × amount == the value the helper would
  hint
- NEVER overwrites a concrete answer

Post-rewrite to commit the computed value with the proof's
source quotes, exactly as TSI-1d does for age. Hint stays; the
closure only acts when the LLM ignored it and abstained.

Designed against the future Phase-2 interface: a
`commit_closure(proof, llm_answer) -> answer | None` shape so the
registry can later own ALL closures (role / temporal / age /
cashback) uniformly. But shipped as a cashback-specific function
now, since that is the only evidenced target.

Verification (1c): 9aaed6a3 multiple smokes — abstain should be
stably rewritten to $0.75; negatives unaffected. No n=100.

## Files

- Telemetry runs: `bench/end_to_end/tc1a-{bb7c3b45,gpt4_d12ceb0e,9aaed6a3}-r{1,2,3}.json`
- Runner telemetry: `run_longmemeval_mem0.py` helper_hints (6785b3e)
- Prior: `2026-05-30-selfanchor-2b-closeout-cc.md` (trust-gap first isolated)
