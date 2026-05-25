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

**Failure layer (revised TWICE — final form per AAS-1 live probe)**:

The first revision (Codex 2026-05-25) proposed
`skill_anchor_subject_disambiguation`: skill receives both
user-owned and family-owned graduation candidates, picks
wrong one. AAS-1 live probe falsifies the premise:

- `_find_event_mentions("graduated from college", retrieved)`
  on the audit sandbox returns **only 2 candidates**, BOTH
  family-graduations (niece x2, same event in event + dialog
  form). User-owned graduation NOT present.
- Searching the entire c18a7dc8 haystack for first-person
  graduation markers ("i graduated", "my college", "my
  degree", "when i was", "years old", "my graduation", etc.)
  returns **0 user-owned graduation mentions**.
- Gold-marked user session (`answer_2e2085fa_1/_2`) contains
  age ("32-year-old Digital Marketing Specialist") and
  "in the industry for a while", but NO explicit
  "I graduated from college on [date]" statement.
- Gold=7 appears to depend on assuming standard US
  graduation age 25 and computing 32 − 25 = 7. This is
  knowledge external to the haystack text.

**Final label**: `gold_or_input_limitation`. The text does
not contain the data required to compute gold=7
deterministically; the gold relies on an implicit
common-knowledge assumption about graduation age.

**Subject-ownership filter** would NOT have saved this qid,
because there is no user-owned graduation event to filter
TO. The filter is still a sound idea for age_interval
robustness in general (would prevent picking niece's
graduation as an anchor when there's no better candidate),
but it cannot be justified on c18a7dc8 alone — needs
broader LME-S survey for qids where user-owned and
family-owned graduations coexist before pursuing.

**Historical context**: `age_interval.py:191` documents
"c18a7dc8 had ~60-80% V6.1 PASS" — under text-only inputs,
this is the LLM probability of guessing the standard
graduation age correctly. V8.2.1 single-run PASS was at the
lucky end of that LLM-guess distribution. There is no
text-grounded path to a deterministic answer.

### b46e15ed — "How many months have passed since I participated in two charity events in a row, on consecutive days?" (gold=2)

**Skill firing**: trinity fallback (no skill produced a
structured answer):

```
ATTENTION-ROUTED TRINITY VIEW (three opposing stances reconciled;
trust this over hedging unless retrieval contradicts):
- answer: Insufficient evidence to determine months since
  participating in two ...
```

**Failure layer (revised per Codex 2026-05-25)**: NOT a
simple `match()` miss. `EventIntervalSkill.match()`
currently returns `True` unconditionally
(`event_interval.py:299`). The real limit is in
`resolve()`: the operator it implements is "interval between
event A and event B" — a delta between two distinct events.

b46e15ed asks "how many months have passed since [a streak
of two consecutive-day charity events]". That's
**reference_date − event_cluster**, not event_A − event_B.
Treating the streak as two separate events and computing
A−B would yield "1 day" (consecutive days), not "2 months
since the streak ended". The shape itself is
out-of-scope for the current operator, not a regex gap.

**Recommended workstream label**: `event_cluster_interval_shape_gap`.
Decision is operator-level, not regex-level:

- Option A: add a new operator
  `elapsed_since(consecutive_event_cluster)` that takes a
  cluster identifier and computes
  `reference_date − cluster.last_event_date`.
- Option B: document this shape as out-of-scope and
  rely on the LLM/trinity path.

Option A is only justified if a broader set of qids shares
the "elapsed-since-cluster" shape. **Pre-audit needed**
before any impl: scan LME-S + LoCoMo for other "since [a
streak of N events]"-shaped queries. If b46e15ed is a
one-off, defer. If it's a recurring pattern, design the
operator. Read-only audit first.

### gpt4_93159ced_abs — "How long have I been working before I started my current job at Google?" (gold = "not enough information")

**Skill firing**: NO age / event-interval skill. Falls
through to trinity, 3-round (because `wants='date'`):

```
ATTENTION-ROUTED TRINITY VIEW:
- answer: 4 years and 3 months of work experience before starting at Google
```

**Failure layer (revised per Codex 2026-05-25)**: NOT a
classification regression. `analyze_with_trinity` calls
`analyze()` first, which deterministically routes "how long"
to `wants='date'` via `_TEMPORAL_RE` (`attention.py:73`). For
queries the regex doesn't classify as `lookup`, the trinity
short-circuits without re-classifying
(`attention.py:461`). So `wants='date'` is the *intended*
classification — and it's correct in the general case (most
"how long have I been Xing before Y" queries are legitimate
date-arithmetic when Y actually happened).

The real gap is at **commit time**: the date-arithmetic
trinity does not verify that Y (the second temporal
endpoint) has actually occurred. For gpt4_93159ced_abs the
user has NOT started at Google yet, so the duration is
literally undefined — but multi-round trinity over-commits
to "4 years 3 months" anyway.

**Recommended workstream label**: `temporal_endpoint_support_gap`.
Add a support-aware commit gate, mirroring V8.2.2a's
role-mismatch guard: before emitting a date-arithmetic
answer, verify that BOTH endpoints have evidentiary support
(a memory says event happened, or memory + reference_date
implies it). When the second endpoint is presupposed but
unevidenced (or contradicted by "haven't started yet"),
emit an abstain / informed-refusal. This keeps the date
skill firing for legitimate duration questions and only
blocks the over-commit case.

NOT to be done: re-routing "how long ... before Y" to
inference. That breaks valid duration questions where Y did
happen.

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

Updated taxonomy (post-LSA-3 + AAS-1 live probe):

| label | count | qids |
|---|---|---|
| gold_or_input_limitation | 4 | 1c0ddc50, b6025781, d6233ab6, **c18a7dc8 (moved after AAS-1)** |
| event_cluster_interval_shape_gap | 1 | b46e15ed |
| temporal_endpoint_support_gap | 1 | gpt4_93159ced_abs |
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
- **Two follow-up workstream proposals (revised after AAS-1)**:
  1. **PRIORITY 1**: `temporal endpoint support gate` —
     read-only design + small-scale validation. For
     `gpt4_93159ced_abs`: before emitting a date-arithmetic
     answer, verify both temporal endpoints are
     evidentiarily supported. Same core idea as V8.2.2a
     role-mismatch support-aware guard, applied to temporal
     commit. Now the highest-priority concrete fix:
     existing skill machinery + narrow deterministic
     guard + clear positive case (gold=abstain text exists).
  2. **DEFER**: `b46e15ed event_cluster_interval`. Pre-audit
     needed to determine if "elapsed-since-cluster" shape
     recurs in more than one qid; if one-off, don't extend.
  3. **DROPPED (per AAS-1 live probe)**: `age_interval
     subject-owned anchor` for c18a7dc8. The probe showed
     `_find_event_mentions` returns only family-graduation
     candidates because the haystack has no user-owned
     graduation event. A subject-ownership filter has
     nothing to filter TO on this qid. Filter may still
     be useful on other qids; needs broader LME-S survey
     before justified.

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
