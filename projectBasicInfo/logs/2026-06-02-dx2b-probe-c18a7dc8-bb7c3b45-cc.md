# DX-2b read-only probes: c18a7dc8 + bb7c3b45 (failure-layer localization)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Read-only diagnose probes (authorized, narrow scope: localize layer
only, no fix, no code change, no n=100). c18a7dc8 current-build probe COMPLETED;
bb7c3b45 live probe did not finish (LLM-latency wall) — bb7c3b45 result is from
the existing May-29 diagnose rec (provisional) + the e2e overlay.

---

## Purpose
Per the #3 audit, decide for two Family-C qids whether the failure is
`retrieval_gap` (proof inputs absent) vs `answer_or_judge_path` (present but
distrusted) vs `helper_refusal` (helper gate refused). DX-2b `--e2e-result`
overlays the saved e2e final answer onto the path_summary.

## c18a7dc8 — age_interval committer (AUTHORITATIVE, current-build)
`diagnose-c18a7dc8-dx2b.json`, `--e2e-result lme-s-n100-v6.1.1...json` (a run
where it FAILED).

- **retrieval: gold 5/5 in top-30** → not a retrieval gap.
- **closure_decision.age_interval: `proof_available: true,
  would_commit_on_abstain: true, would_overwrite_concrete: false`** → on current
  main the committer IS ready and WOULD commit "7" (the correct answer) on a
  pure abstain.
- hint-gate still refuses (`current_age_not_in_retrieved`) — but the committer
  path and the hint path are **two different gates**; the committer's
  answer-independent proof resolved even though the strict hint gate didn't.
- e2e (historical v6.1.1) = pure abstain "The information provided is not
  enough."
- **diagnosis.layer = `answer_or_judge_path`** ("proof was ready but final
  answer wrong").

**Reading (pre-verification):** NOT retrieval. closure_view shows the committer
would rescue a *pure abstain* to "7". Hypothesis was: likely already realized on
main; confirm with a fresh run.

### FRESH-RUN VERIFICATION (2026-06-02) — hypothesis REFUTED
`fresh-c18a7dc8-verify.json` (current main, deepseek-v3.2/dashscope answer,
gpt-4o/openrouter judge, single qid):
- **correct: false** — still fails on current main.
- **answer = "You are 0 years older than when you graduated from college."**
  (gold 7) — `answer_pure_abstain: false`. The live answer-LLM gives a
  **confident concrete WRONG value (0)**, not an abstain.
- Therefore `is_commit_abstain_candidate(answer)` is False → **commit_on_abstain
  does NOT fire** (by design it only rescues pure abstains, never overwrites a
  concrete answer). The committer being "ready" is irrelevant here.
- `helper_hints`: age_interval not in the tracked-hint set and no hint fired;
  the answer-LLM did its own (wrong) arithmetic → "0".

**Corrected conclusion: do NOT downgrade c18a7dc8.** It still fails on main, and
the failure MODE differs by run: v6.1.1 = pure abstain (committer-rescuable),
fresh = **concrete overcommit to a wrong value (0)** (NOT in commit_on_abstain's
polarity — that's the suppressor family's shape, but age_interval is a
committer). So the DX-2b overlay's `answer_or_judge_path` label was right that
it's not retrieval, but "already realized on main" was wrong: the committer
covers only one of the two failure modes this qid exhibits.

**Real lever for c18a7dc8:** upstream of the committer — either make the
age_interval hint actually fire AND be trusted so the answer-LLM emits 7, or add
a guard that detects the concrete-wrong "0" (suppressor-shaped), which is a
different closure family than the existing committer. Not a quick win; left as a
documented headroom candidate, no fix opened.

## bb7c3b45 — savings (PROVISIONAL, May-29 rec + overlay)
Live probe stalled on LLM latency before writing; used existing
`diagnose-bb7c3b45.json` (May-29 build, no `closure_view`) + overlay.

- **retrieval: gold 6/30, 23/200** → not a retrieval gap.
- savings helper_proof: `fired: false`,
  `refusal_reason: paid_anchor_not_found_in_user_turns`,
  `retail_amounts: [500.0]` (found), `paid_amounts: []` (NOT found),
  `computed_saving: null`. Gold is $300 → paid ($200) anchor missing.
- savings is **hint-only — there is no savings committer** (closure_view lists
  only cashback + age_interval committers), so there is no commit-on-abstain
  rescue. Abstain stands.
- **diagnosis.layer = `helper_refusal`** (savings:
  paid_anchor_not_found_in_user_turns).

**Reading:** a genuine current gap, but the lever is **anchor extraction**
(pull the *paid amount* from the retrieved user turns — retail price is already
extracted), NOT retrieval breadth and NOT answer-LLM trust. Provisional until a
current-build probe confirms; re-run when the LLM endpoint is healthy.

## Cross-cutting findings

1. **Family C is NOT one lever.** The two qids differ:
   - c18a7dc8 = committer already ready on main; historical fail is stale →
     verify-with-fresh-run, not fix.
   - bb7c3b45 = real gap in **numeric-anchor extraction** within retrieved
     sessions (paid-amount), and being hint-only it has no committer to rescue.
   Neither is a retrieval-breadth problem (both have gold in top-30), refining
   the audit's "retrieval reliability OR trust" into a third, more precise
   lever: **anchor/fact extraction between retrieval and closure.**

2. **`closure_view` is decisive and only exists on current-build recs.** The
   old May-29 rec lacks it, so an offline overlay on the old rec mislabels
   c18a7dc8 as `helper_refusal` (falls through to refused[0]); the current-build
   rec correctly reaches `answer_or_judge_path` via the committer. → For
   accurate triage, regenerate the diagnose rec on current build first; the
   DX-2b overlay itself is then instant.

3. **DX limitation (matches the audit's "unknown → need more fields" bucket):**
   `diagnosis.reason` is driven by `deterministic_layer.refused[0]`, which can
   name an irrelevant helper (e.g. "savings no_trigger_match" for an
   age_interval qid). The qid-relevant signal lives in `closure_view` +
   `helper_proofs[<relevant helper>]`, not in `refused[0]`. A future DX tweak
   could rank the refusal by the routed/relevant helper.

4. **Operational:** live `diagnose_qid` probes are LLM-latency bound (~25 min
   for one qid here; the second stalled). They are not interactive-fast right
   now. Fast path = build_path_summary offline on a current-build rec.

## Decision
No fix opened (per scope).
- c18a7dc8: fresh single-qid run DONE → **still fails on main** (concrete-wrong
  "0", not abstain → committer can't rescue). NOT downgraded; remains a headroom
  candidate whose lever is upstream (hint-fire+trust, or a suppressor-shaped
  guard), not the existing commit_on_abstain. No fix opened.
- bb7c3b45: regenerate its current-build diagnose rec when LLM is healthy to
  confirm `helper_refusal` / paid-anchor extraction; only then consider whether
  paid-amount extraction is worth a workstream.

## Files
- `bench/end_to_end/diagnose-c18a7dc8-dx2b.json` (current-build diagnose rec)
- `bench/end_to_end/fresh-c18a7dc8-verify.json` (fresh single-qid run; FAIL,
  concrete-wrong "0")
- (bb7c3b45 current-build rec NOT produced — live probe stopped)
