# Quantitative-turn retrieval cohort audit (read-only)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Read-only cohort audit. No code change, no retrieval change. Answers
one question before any ranking work: how many LME-S fails share bb7c3b45's
shape — "gold session retrieved, but the key number-bearing turn out-ranked out
of top-k"? Method = pass-rate over the consistent 13-run set + dataset evidence
shape per qid. Mechanism was directly probe-confirmed only for bb7c3b45; the
others are classified by dataset shape (a probe each would confirm, but is not
needed for the park/go decision).

---

## Candidate set
Quantitative-combination questions (gold numeric/$/duration, question asks how
much/many/old/total/weeks…) with chronic pass-rate <60% on the 13-run set:

| qid | pass | gold | mechanism | bb7c3b45 shape? |
|-----|------|------|-----------|-----------------|
| bb7c3b45 | 38% | $300 | 2 scattered value anchors (retail $500 s42 / paid $200 s14, different sessions); paid turn out-ranked out of top-30 | **YES (probe-confirmed)** |
| 6e984301 | 20% | 3 | 2 scattered *date* anchors (class-start / tool-purchase), interval | maybe (needs probe; could be temporal-hop) |
| d851d5ba | 46% | $3,750 | **aggregation sum** of charity amounts across 5+ sessions | no — breadth/coverage, not one missing turn |
| 370a8ff4 | 0% | 15 | **multi-hop temporal**: count to the 10th jog + flu-recovery date | no — nth-event resolution |
| b46e15ed | 38% | 2 | **multi-hop temporal**: find two charity events on consecutive days + now | no — event-cluster detection |
| c18a7dc8 | 38% | 7 | **concrete overcommit** (answers "0", not a missing anchor) | no — hint-trust / committer-bypass (DX-2c) |

(`gpt4_d6585ce8` excluded — it is OrderedEventList ordering; the numeric match
was just "1." in the gold list.)

## Finding
The bb7c3b45 mechanism — *number-bearing turn out-ranked while the gold session
is otherwise retrieved* — is **NOT a stable cohort**. It is clearly just
bb7c3b45, plus at most 6e984301 (unconfirmed, and possibly temporal-hop). The
other four quantitative chronic-fails fail for **distinct, individually small
mechanisms**:
- aggregation breadth (d851d5ba) — need ALL of N amount turns; this is the
  known "聚合计数类" shape (top-k breadth, not ranking).
- multi-hop temporal (370a8ff4, b46e15ed) — nth-event / consecutive-day /
  relative-time resolution; the hard part is event resolution, not numeric-turn
  ranking.
- concrete overcommit (c18a7dc8) — answer-LLM computes a wrong value; no missing
  turn (DX-2c `concrete_wrong_bypassed_committer`).

So a "quantitative-turn retrieval weighting" change would be a high-blast-radius
ranking edit (it perturbs ordering for many questions) to fix essentially **1**
qid. Cost/benefit is poor and the negative-control risk is real.

## Decision: PARK quantitative-turn retrieval weighting
Per the pre-agreed rule (cohort 1-2 → park), the retrieval-ranking direction is
parked. Do NOT implement turn weighting. bb7c3b45 stays a documented single-qid
retrieval-ranking instance; if it ever recurs as a larger cohort (e.g. a future
dataset or a new helper family that needs paired numeric anchors), revisit with
this audit as the baseline.

The broader takeaway reinforces the #3 audit: the LME-S tail is not one lever —
it is several small, distinct mechanisms (structural floor, temporal multi-hop,
aggregation breadth, concrete overcommit, single-turn ranking), none large
enough alone to justify a global change. This is the evidence-based stopping
point for bench optimization.

## Next (suggested)
With bench optimization parked, the higher-value direction is productization /
consolidation of what is now stable:
- target-pack = e2e gate (manual, after key-path changes)
- regression-pack = deterministic gate (every change)
- diagnose_qid + path_summary (DX-2a/2b/2c) = failure-path debugger
- ProofResult / commit_on_abstain / SelfAnchor / closure_view boundaries
No code changed in this audit.
