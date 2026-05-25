# CQ-3 Design — Structural Candidate-Block Suppress Rule

**Date**: 2026-05-25
**Author**: Claude Code
**Status**: Design only. NOT implemented. Pre-audit gate defined.

---

## Why Suppress, Not Re-rank

CQ-1 corrected (M1 1/10 → 1/10) falsified the "narrow re-rank
fix" hypothesis: removing 17 known junk slots just unveils 6
generic framing tokens that the same prompt position now
displays to the LLM. Re-ranking the existing candidate set
doesn't improve answer commit because the candidate set itself
is too low-information when the question doesn't decompose
cleanly into one of the extractors' shapes.

The architecturally consistent move is **don't inject a
candidate block when the candidate set is structurally weak**.
This matches the V8.2.x / V8.3.1 / NAR pattern: narrow
deterministic helpers fire ONLY when their inputs are
strongly supported, otherwise stay silent.

The change point is `render_evidence_candidates(candidates)`
(or its single call site in `run_locomo_mem0.py`): wrap with
a deterministic suppress check that returns `""` when the
top-K does not meet a support threshold.

## Gate the Suppress Rule Must Satisfy

Per user audit:

- **Structural only**: based on properties of the candidate
  set itself (counts, scores, diversity). No qid-specific
  branches, no answer-token awareness, no stopword stacking.
- **Explainable, low support**: each suppress decision must
  be traceable to a small set of clearly named metrics
  ("max confidence < X", "no candidate has source diversity
  > Y", etc.). Not a learned threshold, not a model call.
- **At-least-one e2e improvement before merging**: pure
  ranking simulation is not sufficient evidence; v1 already
  failed that bar.

## Candidate-Set Health Signals

Looking at the CQ-1 dump across 10 flip10 qids:

1. **Max confidence cap**: `proper_noun_in_context` /
   `series_or_entity_name` / `activity_target` candidates
   carry conf 0.5-0.75. `topic_keyword` conf 0.7. Date /
   relative_marker conf 0.85. Financial_indicator conf 0.7.
   A candidate set whose top-1 confidence is ≤ 0.6 is
   structurally low — the extractors didn't find anything
   they assigned high confidence to.
2. **Relation diversity**: when the top-5 candidates all
   share the same `relation` (e.g., all
   `proper_noun_in_context`), the set is showing one
   over-active extractor with no second-channel
   corroboration. Genuine evidence usually surfaces from
   ≥ 2 extractor types.
3. **Source-count uniformity**: when top-5 all have
   `source_count == 1`, the set has no cross-memory
   triangulation. Combined with low confidence, this is
   noise.
4. **Absence of a "high-floor" candidate**: when no
   candidate in the full ranked list (not just top-5)
   reaches conf ≥ 0.7 AND `source_count ≥ 2`, there is no
   single candidate with both decent confidence AND any
   triangulation.

## Suppress Rule (proposed v1 — to be tested by audit)

`render_evidence_candidates()` returns `""` (no inject) when
ALL of the following hold:

```
top1.confidence <= 0.6
AND
no candidate in the full list has (confidence >= 0.7 AND source_count >= 2)
```

Rationale:

- Two-clause AND keeps false-suppress low: if any "high-floor"
  candidate exists, we still inject (its presence means at
  least one strong signal survived re-rank).
- The 0.6 ceiling is the natural confidence boundary in the
  current extractor — anything below that is "proper-noun /
  activity-target" without role-verb confirmation, which is
  exactly the artifact-prone category.
- No qid awareness, no answer-token check, no stopword
  list. Pure properties of the (candidate, relation,
  source_count, confidence) tuples.

## Pre-merge Decision Tree

1. CQ-3 audit (read-only): for each of the 10 flip10 qids,
   compute the rule. Output: how many qids are suppressed?
   How many of them are
   (a) stable-PASS today (suppressing risks regression),
   (b) stable-FAIL today (suppressing can only flat or help),
   (c) currently polluted by candidate injection (Nate /
   Tilly question / etc., where the LLM is being misled by
   noisy candidates)?

2. **Audit gate**:
   - If suppress fires on ANY stable-PASS qid → STOP. The
     rule as written would regress e2e. Either revise or
     close CQ-3 without implementation.
   - If suppress fires only on stable-FAIL and/or polluted
     qids → continue.

3. **e2e gate**: spawn focused e2e smoke on the suppress-
   candidate qids + the 3 stable controls (c2_Maria,
   c3_Tilly-question, c4_Seattle). Verify:
   - ≥ 1 currently-FAIL qid passes under suppress.
   - All 3 stable controls remain PASS.

4. **Only if both gates pass** does CQ-3 enter
   implementation (CQ-4) as a single conditional in
   `render_evidence_candidates` plus tests.

## What CQ-3 Will NOT Do

- Will NOT extend stopword sets.
- Will NOT change `_PROPER_NOUN_RE` extraction surface.
- Will NOT touch retrieval scoring or query decomposition.
- Will NOT inspect or branch on the question text beyond
  passing it through unchanged.
- Will NOT pre-commit to merging if the audit gate is met
  but the e2e gate is not. (The cost of a prompt-side
  change that doesn't actually improve e2e is real and was
  the explicit lesson of CQ-1.)

## Open Risks

- The 0.6 / 0.7 / 2 thresholds are picked from observing
  the current confidence vocabulary in `evidence_candidates.py`.
  If the extractor ever grows new relation types with
  different confidence calibrations, these thresholds may
  drift out of meaningfulness. Mark the constants as
  load-bearing at the call site so future changes notice.
- Suppression removes a hint the LLM might still have used
  on truly low-information cases where the answer is itself
  noisy. The e2e gate is what guards against this; the rule
  alone cannot.

## Next Step

Implement CQ-3 audit (extend `cq1_candidate_quality_audit.py`
with an M4 "would be suppressed" column). Run on sc3 sandbox.
Report whether stable-PASS qids would be wrongly suppressed.

Audit is read-only and structural; can be re-run in seconds.
No e2e or LLM dependency at this stage.
