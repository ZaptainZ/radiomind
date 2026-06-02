# DX-2b read-only probes: c18a7dc8 + bb7c3b45 (failure-layer localization)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Read-only diagnose probes (authorized, narrow scope: localize layer
only, no fix, no code change, no n=100). Both c18a7dc8 and bb7c3b45 current-build
probes COMPLETED (bb7c3b45 re-run succeeded once the LLM endpoint recovered).
c18a7dc8 additionally got a fresh single-qid run; bb7c3b45 got a dataset
root-cause dig. No fix opened.

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

## bb7c3b45 — savings (CONFIRMED, current-build probe)
`diagnose-bb7c3b45-dx2b.json` (current build, with `closure_view`).

- retrieval: gold 6/30, 23/200.
- savings helper_proof: `fired: false`,
  `refusal_reason: paid_anchor_not_found_in_user_turns`,
  `retail_amounts: [500.0]` (found), `paid_amounts: []` (NOT found),
  `computed_saving: null`.
- savings is **hint-only — no savings committer** (closure_view: only cashback
  + age_interval), so no commit-on-abstain rescue. Abstain stands.
- **diagnosis.layer = `helper_refusal`** (savings:
  paid_anchor_not_found_in_user_turns).

### Root-cause dig (dataset evidence) — it IS a retrieval problem
Both anchors exist in USER turns, in **different sessions**:
- retail $500 — s42 t0 "...Jimmy Choo heels, which I know originally retailed
  for $500" → **retrieved** (preview rank 2) → extracted ✓.
- paid $200 — s14 t0 "...my new Jimmy Choo heels that I got at the outlet mall
  for $200" (and s14 t1 "for $200 is a steal!") → **NOT in top-30**.
- $500 − $200 = $300 = gold.

Decisive nuance: gold session s14 **is** partially retrieved — but only its
*fluffy outfit-advice turns* (LBD r14, necklace r22, hair r13/r21). Its
*quantitative* turns (t0/t1, carrying "$200") rank BELOW the chatty turns and
fall out of the window. So `paid_anchor_not_found_in_user_turns` is because the
paid turn was **never retrieved**, not (primarily) because the parser can't read
"got ... for $200".

**Corrected reading (supersedes the provisional "anchor extraction, NOT
retrieval" note):** the lever is **retrieval granularity/ranking** — the
number-bearing turn under-ranks vs same-session chatter, so the proof input
never reaches the savings helper. This is a concrete instance of the #3 audit's
"retrieval reliability of proof inputs" / 第四律 lever, NOT a quick
extraction-regex tweak (improving the parser is moot when the turn isn't
recalled). Higher effort than a "small fix"; left as a retrieval-side headroom
candidate, no fix opened.

## Cross-cutting findings

1. **Family C is NOT one lever.** The two qids fail for entirely different
   reasons:
   - c18a7dc8 = answer-LLM **concrete-overcommits to a wrong value (0)**; the
     ready committer can't help (abstain-only polarity). Lever is upstream
     (hint fire+trust, or a suppressor-shaped guard).
   - bb7c3b45 = the **quantitative proof turn ($200 paid) is never retrieved**
     (out-ranked by same-session chatter), so savings can't compute; hint-only,
     no committer rescue. Lever is **retrieval granularity/ranking** (第四律).
   Same Family-C bucket, opposite mechanisms and opposite fix directions —
   confirming the audit's point that "Family C" is a label for a band, not a
   single fixable cause.

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
- bb7c3b45: current-build diagnose DONE + dataset dig → root cause is
  **retrieval ranking** (the $200 paid turn under-ranks vs same-session chatter
  and never reaches the savings helper), not extraction. NOT a small fix; it is
  a retrieval-side headroom candidate (第四律). No fix opened.

## Files
- `bench/end_to_end/diagnose-c18a7dc8-dx2b.json` (current-build diagnose rec)
- `bench/end_to_end/fresh-c18a7dc8-verify.json` (fresh single-qid run; FAIL,
  concrete-wrong "0")
- `bench/end_to_end/diagnose-bb7c3b45-dx2b.json` (current-build diagnose rec;
  helper_refusal, paid turn not retrieved)
