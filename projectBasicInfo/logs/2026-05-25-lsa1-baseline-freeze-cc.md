# LSA-1 — LME-S Deterministic Skill Audit, Baseline Freeze

**Date**: 2026-05-25
**Author**: Claude Code
**Status**: Freeze. No code change. Document only.

---

## Purpose

Lock the current state so the follow-up failure inventory
(LSA-2) and skill-candidate filter (LSA-3) operate on a
stable scope. Any qid already addressed by a shipped helper
is OUT of scope; any qid that requires architectural work
beyond a narrow deterministic skill is OUT of scope.

## Frozen State

| field | value |
|---|---|
| `main` HEAD | `e68a665` |
| `origin/main` | synced |
| Repo tests | 596 passed |
| Latest contemporary LME-S n=100 baseline | `lme-s-v822a-n100.judge-fixed.json`: 0.92 (deepseek-v3.2 answer / gpt-4o judge, 2026-05-20 era) |
| Older contemporary LME-S n=100 baseline | `lme-s-v82-1-n100.json`: 0.92 (V8.2.1 era) |
| `main` (post-V8.3.1 + NAR) n=100 | **NOT measured** — incremental wins inferred from target smokes only |

## Already-Addressed Target Qids (OUT OF AUDIT)

These have shipped deterministic helpers; do not include in
LSA-2 / LSA-3 / LSA-5:

| qid | helper | smoke evidence |
|---|---|---|
| `031748ae_abs` | `role_mismatch_guard` (V8.2.2) | SC-2 3/3 PASS |
| `9aaed6a3` | `cashback_arithmetic_hint` (V8.2.3a) | SC-2 3/3 PASS, e2e 1.000 |
| `gpt4_d12ceb0e` | `person_age_average_hint` (V8.3.1) | SC-2 3/3 PASS, e2e 1.000 |
| `d851d5ba` | `detect_charity_amounts` (NAR) | SC-2 2/3 (fix v1) → 3/3 expected (fix v2 verified isolated 3/3 + e2e 1.000) |

## Excluded Errata (RUNTIME-FILTERED, OUT OF AUDIT)

| qid | reason |
|---|---|
| `370a8ff4` | dataset-gold errata, harness filters at run-time |

## Out-of-Scope Failure Categories

Per Codex (2026-05-25), the following failure shapes should
NOT consume LSA effort, even if discovered in the inventory:

1. **Retrieval-bridging-recall** (gold-in-store but not in
   top-K). The c2_financial / c9_Calvin family. Methodology
   workstream; LLM-heavy; not narrow-deterministic.
2. **Dataset-gold quality / errata** candidates. e.g.,
   c3_2656e2c771 (count mismatch with same-dialogue "third"
   statement); c5_Voyageurs (text-channel-absent gold).
   Bench-errata mechanism, not RadioMind code.
3. **Preference / advice / inference** answers (e.g.,
   d6233ab6-style). Not extractable as typed events.

## In-Scope Failure Shape (LSA Target)

A qid is an LSA-pilot candidate IFF:

1. Gold-bearing memory IS in retrieve top-K under default
   `a2a-practice` (no agentic) on current main.
2. Gold answer is derivable by a deterministic operator over
   typed events / structured extractions
   (sum / count / mean / product / ordering / lookup).
3. The trigger / operator can be written as a query-shape
   family (e.g., "average X across kin set" / "how many X
   replaced") that won't qid-match.
4. The intervention either extends an existing layer
   (`NumericAggregator` recall on a non-charity class,
   `evidence_candidates` for a new query-shape) or is a
   single narrow helper similar to the four already shipped.

## LSA-2 Scope

LSA-2 will:

1. Take the union of fail qids from `lme-s-v82-1-n100.json`
   and `lme-s-v822a-n100.judge-fixed.json` (most-contemporary
   measurements).
2. Subtract the 4 fixed targets and the errata qid.
3. For each remaining fail qid, label according to Codex's
   4 buckets:
   - `retrieve_missing` (gold-bearing memory absent from
     top-K)
   - `evidence_present_computation_missing` (gold-bearing
     memory in top-K, but answer requires a deterministic
     operator no current skill performs)
   - `commit_variance` (gold-bearing memory in top-K AND a
     skill could compute, but the LLM commits to a wrong
     answer)
   - `gold_or_input_limitation` (benchmark spec / non-text-
     groundable / inference-only)
4. Persist structured JSON for follow-up audits.

LSA-2 is offline / read-only. No LLM calls beyond optional
retrieve probes if a sandbox is reusable.

## LSA-3 Gate (preview)

From the LSA-2 inventory, keep only
`evidence_present_computation_missing` candidates that also
satisfy the in-scope filter above. Drop everything else.
Even within `evidence_present_computation_missing`, the
proposed operator must be expressible as a family guard
(LSA-3 narrow rule).

## LSA-4 / 5 / 6 Notes

LSA-4: prefer extending existing `NumericAggregator` /
typed-event infrastructure over new helpers. Pilots that
only need a new class definition + recognizer (the NAR
shape) are highest-priority.

LSA-5: at most one pilot per LSA cycle. Cycle precedence:
amount aggregation > rate multiplication > age arithmetic >
exact ordering > entity-normalization-required count >
preference inference. (User-supplied.)

LSA-6: smoke + negative + trigger-face audit only. **No
n=100** before a narrow-trigger audit confirms <5% global
surface. Pre-NAR-like discipline.

## What This Freeze DOES NOT Promise

- Doesn't claim current main beats V8.2.2a 0.92 baseline.
  The 4 fixed targets' incremental gains are individually
  verified; aggregate is inferred.
- Doesn't claim every fail outside the 4 targets is
  audit-worthy. LSA-2's categorization will likely show a
  significant fraction in
  `retrieve_missing` / `gold_or_input_limitation`, both
  out-of-scope.
- Doesn't commit to opening LSA-5 (pilot) unless LSA-2 →
  LSA-3 produces ≥ 1 in-scope candidate.

## Next Step

LSA-2 audit script + JSON output, then this freeze
becomes the comparator for any future re-measurement.
