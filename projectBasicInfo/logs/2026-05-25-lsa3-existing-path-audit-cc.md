# LSA-3 — Existing-Path Regression Audit

**Date**: 2026-05-25
**Author**: Claude Code
**Status**: Read-only audit complete. **3 of 8 LSA-2 in-scope
fails are NOT retrieve_missing**. Each has a distinct
existing-path issue. No code change in this log — three
follow-up workstream proposals.

---

## Why This Audit

LSA-2 v1 labeled `b46e15ed` and `c18a7dc8` as
`retrieve_missing` from the heuristic "answer abstained";
Codex correctly flagged this as not-proof — abstain could
also be commit-over-cautious or skill-side regression.
`gpt4_93159ced_abs` was labeled `commit_variance` (gold =
abstain, LLM committed) but the existing
abstain/presupposition path coverage was never verified.

This audit probes each of the 3 qids against current
`main` (`e68a665`) to determine the actual layer of
failure.

## Method

Single fresh sandbox; ingested each qid's haystack once
(`run_aggregation=True, run_refinement=False`). For each:

- `mind.search(question, max_results=200)` (matching runner
  `TOP_K`).
- Identify how many of the gold-marked `answer_session_ids`
  appear in top-K and at what ranks.
- Probe each existing helper / skill (`role_mismatch_guard`,
  `cashback_arithmetic_hint`, `person_age_average_hint`,
  `get_numeric_cardinal`, `run_evidence_candidates`,
  `run_temporal_precision`, `run_open_domain_specific`).
- Cross-reference firing output to see which skill, if any,
  produced what.

Artifact: `bench/end_to_end/lsa3-existing-path-audit.json`.

## Results — Retrieve

| qid | gold turns in top-200 | first 5 ranks |
|---|---|---|
| `c18a7dc8` | 5 | [14, 16, 23, 24, 27] |
| `b46e15ed` | 25 | [30, 33, 40, 42, 44] |
| `gpt4_93159ced_abs` | 9 | [2, 5, 18, 22, 28] |

**All 3 qids have gold evidence in retrieve top-30.**
`retrieve_missing` is NOT the layer of failure for any of
them. LSA-2 v1's heuristic conclusion was wrong on this set;
the corrected `needs_retrieve_probe` label was appropriate.

## Per-qid Existing-Path Diagnostics

### c18a7dc8 — "How many years older am I than when I graduated from college?" (gold=7)

**Skill firing**: `age_interval` skill DOES fire with conf=0.90.

```
STRUCTURED SKILL (age_interval, conf=0.90):
- graduated from college → 2023-05-26
- today / ref date → 2025-01-01    (audit artifact; runner passes question_date)
Computed answer: 1
```

**Failure layer**: anchor selection. The skill grabs the
first "graduation" event in retrieve — top-1..13 hits are
KG events about **family members' graduations** (niece's
2023-05-22, colleague's son's 2023-05-10, etc.). The user's
own college-graduation evidence (`answer_2e2085fa_1_t6`)
is at rank 14.

**Historical context**: `age_interval.py` line 191 documents
"c18a7dc8 had ~60-80% V6.1 PASS" — explicitly stochastic.
Line 346 documents "delta=0 vs gold=7 come from round 1".
The V8.2.1 single-run PASS was at the lucky end of that
distribution, not a deterministic fix.

**Recommended workstream label**: `anchor_disambiguation`
(retrieval-side; the relevant evidence is in store but
out-ranked by topically-adjacent third-party events). NOT a
narrow skill-side fix.

### b46e15ed — "How many months have passed since I participated in two charity events in a row, on consecutive days?" (gold=2)

**Skill firing**: NO numeric / age / event-interval skill
fires. Falls through to trinity (3-round, wants=date):

```
ATTENTION-ROUTED TRINITY VIEW (three opposing stances reconciled;
trust this over hedging unless retrieval contradicts):
- answer: Insufficient evidence to determine months since
  participating in two ...
```

**Failure layer**: skill-match gap. `event_interval` skill
(`src/radiomind/skills/event_interval.py`) is designed for
"how many X since event-A and event-B"; its `match()`
predicate should plausibly catch this shape but didn't.
Could be a narrow regex / shape regression.

**Recommended workstream label**: `skill_match_gap` (audit
`event_interval.match()` against b46e15ed's question shape;
either widen the predicate or document why this shape is
out of scope). Read-only audit first, no implementation.

### gpt4_93159ced_abs — "How long have I been working before I started my current job at Google?" (gold = "not enough information")

**Skill firing**: NO age / event-interval skill. Falls
through to trinity, 3-round (because `wants='date'`):

```
ATTENTION-ROUTED TRINITY VIEW:
- answer: 4 years and 3 months of work experience before starting at Google
```

**Failure layer**: **classification regression**.
`mind.py:1267-1271` docstring explicitly documents this qid:

> "Multi-round trinity ONLY for the `date` wants. Originally
> also wired for `inference`, but n=100 v4 showed multi-round
> on open-ended inference questions causes over-commitment:
> round 1 says 'info not enough', round 2 sees the prior
> stances and 'tries harder', producing a confident but
> wrong answer (gpt4_93159ced_abs). Inference is a divergent
> task — no single right answer to converge to — so
> single-round is correct."

The historical fix was: **inference qtype → single-round
(abstains), date qtype → multi-round (commits)**. Today
`analyze_with_trinity(query, llm=mind._llm).wants` returns
`'date'` for this query, so multi-round fires → over-commit.

If classification ever returned `'inference'` for this
question (it asks "how long have I been working before X",
which is an inference about working duration), single-round
trinity would have abstained correctly.

This is a **likely classification regression in attention**:
either V8.x stacking changed the trinity prompt, or the
LLM's behavior shifted. The fix-side machinery is in place;
only the upstream classifier flipped.

**Recommended workstream label**: `attention_classification_regression`
(read-only diagnose: under what condition does
`analyze_with_trinity` classify this question as `date` vs
`inference`? If reliably classifiable as inference by a
deterministic regex / shape rule, that's the narrow fix).

## Implications for LSA Roll-up

LSA-2 v1 wrote "LME-S narrow optimization converged on this
baseline" with caveats. The audit reveals:

- **3 of 8 in-scope fails are existing-path regressions or
  near-misses**, not retrieve_missing or gold-quality.
- Each has a distinct fix shape (`anchor_disambiguation`,
  `skill_match_gap`, `attention_classification_regression`).
- None matches the "narrow deterministic helper" mold of the
  four shipped (role_guard / cashback / age_avg / charity);
  these are **integration / wiring** problems on existing
  skills, not new skill design.

Updated taxonomy (post-LSA-3):

| label | count | qids |
|---|---|---|
| gold_or_input_limitation | 3 | 1c0ddc50, b6025781, d6233ab6 |
| anchor_disambiguation | 1 | c18a7dc8 |
| skill_match_gap | 1 | b46e15ed |
| attention_classification_regression | 1 | gpt4_93159ced_abs |
| computation_high_risk | 1 | gpt4_ab202e7f |
| evidence_present_computation_missing | 1 | gpt4_d6585ce8 |

LSA-2 v1's "no LSA-5 pilot recommended" still stands for the
"narrow new helper" workstream. But the 3 existing-path
issues identified here justify three NEW (separate,
non-LSA-shaped) audit/fix workstreams. None auto-started.

## Decision

- **LSA-2 v1 wording revised**: the conclusion "LME-S narrow
  deterministic optimization is converged" is too strong.
  Convergence holds for **new narrow helpers**, but
  **existing-path regressions exist** on at least 3 of 8
  remaining fails. These don't match the LSA helper-design
  template; they need wiring / classification audits.
- **No code change in this log**. Each existing-path issue
  needs its own scoped audit before any commit.
- **Three follow-up workstream proposals** (not auto-opened):
  1. `c18a7dc8 / age_interval anchor_disambiguation` —
     read-only audit on how `age_interval` picks the
     graduation anchor; is rank-1 preference correct?
  2. `b46e15ed / event_interval match-gap` — read-only
     audit on `event_interval.match()` predicate; if
     widening the regex catches this shape without
     mis-firing on non-event-delta questions, consider
     impl.
  3. `gpt4_93159ced_abs / attention classification` —
     read-only diagnose: deterministic regex / shape rule
     to route "how long have I been Xing before Y"-shaped
     questions to `inference` (single-round trinity) rather
     than `date` (multi-round trinity).

Each warrants its own go-ahead. None auto-started.

## Caveats

- 3 qids audit at n=1 sandbox; ingest is stochastic, so the
  retrieve top-K could shift across re-runs. The "gold in
  top-30" finding is qualitatively robust because all 3 had
  ≥5 gold turns in top-30, but exact ranks may move ±5
  across runs.
- `analyze_with_trinity` involves an LLM call; the
  classification snapshot here ("wants='date'" for all 3)
  may itself be stochastic. A more rigorous check would run
  it ≥ 3 times.
- LSA-3 audit script used a hardcoded `reference_date=
  "2025-01-01"` in the skill-probe section; runner actually
  passes `q["question_date"]` ("2023-05-30" / "2023-04-18").
  This affects only the audit's "Computed answer" field,
  not whether the skill fires.

## Files

- Audit script: `bench/end_to_end/lsa3_existing_path_regression.py`
- Audit data: `bench/end_to_end/lsa3-existing-path-audit.json`
- LSA-1 baseline freeze: `projectBasicInfo/logs/2026-05-25-lsa1-baseline-freeze-cc.md`
- LSA-2 inventory: `projectBasicInfo/logs/2026-05-25-lsa2-failure-inventory-cc.md`
- This log: `projectBasicInfo/logs/2026-05-25-lsa3-existing-path-audit-cc.md`
