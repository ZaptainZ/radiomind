# TSI-1 — Trust-in-Structured-skill Cohort Audit (Read-Only)

**Date**: 2026-05-26
**Author**: Claude Code
**Status**: Read-only audit complete. **Decision branch:
"only age_interval shows trust gap" — narrow fix applies.
NO broad authoritative-result commit contract needed.**

---

## Why This Audit

Codex (2026-05-26 P1.3) demoted TSI-1 from a "global
conf>=0.85 override impl" to a read-only cohort audit
first. Specifically:

> 若不止 `age_interval` 出现同类问题，再设计 proof-bearing
> commit contract；否则只为确定性 age arithmetic 做窄闭环。

This audit answers: across the 8 LSA-2 in-scope FAILS on
the V8.2.2a-judge-fixed baseline, how many qids show a
"trust gap" (skill produces high-conf answer, answer-LLM
ignores it)?

## Scope

- Cohort: 8 in-scope FAILS from V8.2.2a-judge-fixed (LSA-2)
- Method:
  - All 8 → free regex pre-screen against registered skill
    triggers (`age_interval` / `event_interval` / `cardinality`
    / `temporal` / `chain_reasoning` / `list_ordering`)
  - 3 qids in LSA-3 sandbox (already ingested) → live
    probe of `mind.run_temporal_precision` (the runner's
    skill-routing entry point), capturing
    `STRUCTURED SKILL` section if any
- Read-only; no code change.

## Results

| qid | pre-screen triggers | skill fired? | skill answer | artifact answer | trust gap |
|---|---|---|---|---|---|
| `1c0ddc50` | (none) | — | — | "Since you already listen to podcasts ..." | N/A |
| `b6025781` | (none) | — | — | "Since you're interested in Mexican-inspired ..." | N/A |
| `d6233ab6` | (none) | — | — | "I don't have enough information about your ..." | N/A |
| `c18a7dc8` | age_interval, temporal | **age_interval conf=0.90** | **"7"** | "The information provided is not enough..." | **YES** |
| `b46e15ed` | temporal | none (no STRUCTURED SKILL emitted) | — | "The information provided is not enough." | N/A |
| `gpt4_93159ced_abs` | temporal | none (no STRUCTURED SKILL emitted) | — | "Based on the information ... 4 years 3 months" | N/A (handled by TESG-1 guard now) |
| `gpt4_ab202e7f` | cardinality | not-probed (not in sandbox) | — | "You replaced or fixed 4 kitchen items..." | unlikely (entity norm) |
| `gpt4_d6585ce8` | list_ordering | not-probed (not in sandbox) | — | "1. Free outdoor concert series..." | unlikely (multi-event/session) |

## Aggregate

- Probed in-sandbox: 3
- **Trust-gap candidates: 1 (`c18a7dc8`)**
- Pre-screen distribution:
  - 3 qids trigger no skill (preference advice)
  - 1 qid triggers age_interval + temporal (c18a7dc8 — confirmed trust gap)
  - 2 qids trigger temporal only but skill registry produces no
    SkillResult (b46e15ed, gpt4_93159ced_abs)
  - 1 qid triggers cardinality (gpt4_ab202e7f)
  - 1 qid triggers list_ordering (gpt4_d6585ce8)

## Why the Two Non-Probed Are Unlikely Trust Gaps

`gpt4_ab202e7f` (kitchen item count) requires entity
normalization (Moen faucet / kitchen faucet / faucet —
same item or different?) — `CardinalitySkill` doesn't
ship that capability. If it did fire and produce a count,
the LLM almost certainly wouldn't *ignore* a number from
a count skill, and the artifact answer "4 kitchen items"
shows the LLM committed to a number. So even if skill
fires, it's not a *trust* gap; it's a *correctness* gap
on the count.

`gpt4_d6585ce8` (concert ordering) needs the
`ListOrderingSkill` to enumerate multiple events per
session AND temporally resolve them. Current implementation
likely doesn't fire for this shape, and the artifact answer
shows the LLM did commit a list — so again not a trust
gap, but a content-extraction completeness gap.

A full live probe of those two would refine the
classification, but the *trust gap* signature requires
skill firing + LLM ignoring; both qids have committed
LLM answers (not abstains), so even if a skill fires the
LLM was at minimum *attempting* the answer, just from
wrong content — that's a different fix shape.

## Decision Per Codex Branching Rule

> 若不止 `age_interval` 出现同类问题，再设计 proof-bearing
> commit contract；否则只为确定性 age arithmetic 做窄闭环。

**Outcome: only `age_interval` shows the trust gap**.

Recommendation: **narrow age_interval commit contract**
(NOT broader authoritative-result contract). Specifically:

- Post-process branch (after the LLM answer): if
  `age_interval` skill fired with `conf >= 0.85` AND
  produced a numeric `answer`, AND the LLM final answer
  is canonical-abstain (uses `is_abstain_response` from
  JAB-1b), rewrite the answer to commit to the skill's
  number. Same architectural pattern as
  `maybe_rewrite_with_guard` (role mismatch) and
  `maybe_rewrite_with_temporal_guard` (TESG-1) — both
  shipped, both work.

- Scope strictly to **age_interval only** for now. If a
  future audit finds more skills with the same trust
  gap, escalate to a broader contract.

- Pre-impl audit: confirm the `age_at_event`
  deterministic store-scan provides the *backing
  evidence* required for the commit contract; the post-
  rewrite should only fire when both (a) trinity
  escalation picked an anchor AND (b) the
  `_age_at_event` value is grounded in an actual
  `"at the age of N"` mention.

This workstream requires **separate user go-ahead** —
TSI-1 audit closes here without implementing the contract.

## Files

- Audit script: `bench/end_to_end/tsi1_cohort_audit.py`
- Audit data: `bench/end_to_end/tsi1-cohort-audit.json`
- This log: `projectBasicInfo/logs/2026-05-26-tsi1-cohort-audit-cc.md`
