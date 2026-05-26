# LSA-3 — Existing-Path Regression Audit

**Date**: 2026-05-25
**Author**: Claude Code
**Status**: Read-only audit complete. **3 of 8 LSA-2 in-scope
fails are NOT retrieve_missing**. Each has a distinct
existing-path issue. No code change in this log — three
follow-up workstream proposals.

**Revision history**:
- v1 (2026-05-25): initial audit. Labeled c18a7dc8 as
  `anchor_disambiguation`, gpt4_93159ced_abs as
  `attention_classification_regression`.
- v2 (2026-05-25): per Codex review, relabeled c18a7dc8
  → `skill_anchor_subject_disambiguation`,
  gpt4_93159ced_abs → `temporal_endpoint_support_gap`.
- v3 (2026-05-25 PM): AAS-1 live probe (FLAWED keyword
  search) appeared to falsify the c18a7dc8 premise;
  reclassified to `gold_or_input_limitation`.
- **v4 (2026-05-26): AAS-1 RETRACTED**. Keyword search
  used `"my bachelor"` but the user phrases the fact as
  `"a Bachelor's degree ... completed at the age of 25"`.
  A broader scan finds the deterministic age-25 evidence.
  c18a7dc8 reclassified to
  `age_interval_evidence_priority_gap`; restored to
  priority-1 alongside `temporal_endpoint_support_gap`.

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

**Failure layer (revised THIRD time — AAS-1 finding RETRACTED 2026-05-26)**:

The first revision (Codex 2026-05-25) proposed
`skill_anchor_subject_disambiguation`. AAS-1 (2026-05-25)
"falsified" the premise based on a haystack keyword scan.

**AAS-1 RETRACTION (2026-05-26)**: the keyword search was
buggy. The keyword list included `"my bachelor"` but the
user phrases the fact as `"a Bachelor's degree ... which
I completed at the age of 25"` (note `a`, not `my`). A
broader scan (`"bachelor"`, `"age of 25"`) finds the
turn immediately:

> `answer_2e2085fa_1_t0` (USER): "I have a Bachelor's
> degree in Business Administration with a concentration
> in Marketing from the University of California,
> Berkeley, **which I completed at the age of 25**."

This IS the user-owned, deterministic, in-text graduation
evidence. Gold = current_age (32) − graduation_age (25) =
7 is text-grounded; NOT a common-knowledge assumption.

**Final label (post-retraction)**: `age_interval_evidence_priority_gap`.
The skill already documents this exact paraphrase gap
(`age_interval.py:246`: "When token-overlap fails (e.g.
'graduated from college' ≠ 'completed Bachelor's at age
25')..."). Failure mechanism:

1. `_find_event_mentions("graduated from college", ...)`
   (line 106): tokenization keeps `{graduated, college}`
   after stopword filter; the Bachelor's turn lacks both
   tokens (`completed, bachelor, degree, age, ...`) → score
   0 → not a candidate. Niece's "graduated from high
   school" overlaps on `graduated` → 0.5 ≥ 0.4 → enters
   `b_matches`.
2. `_find_event_via_trinity` escalation (line 246) runs in
   older/younger mode. If it returns `(content, date,
   age=None)` — i.e. picks a date-only memory without
   `at the age of N` — then `b_content` is non-empty.
3. Line 595's explicit `at the age of N` store-scan is
   gated on `if b_content is None`, so it gets skipped
   when escalation set a date-only anchor → the deterministic
   age-25 evidence in `answer_2e2085fa_1_t0` is never read.

**Revised label rationale**: the skill has BOTH a semantic
escalation path AND an explicit `at the age of N` store
scan — the failure is in their *priority*. Explicit
`age_at_event` evidence (deterministic) should be preferred
over date-only anchors found by semantic escalation. This
is an existing-path priority fix, not input limitation.

**Historical context**: `age_interval.py:191` documents
"c18a7dc8 had ~60-80% V6.1 PASS" — consistent with semantic
trinity sometimes picking the user-owned bachelor turn and
sometimes not; not consistent with the (now-retracted)
"text doesn't contain the data" hypothesis.

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

Updated taxonomy (post-LSA-3 + AAS-1 RETRACTION 2026-05-26):

| label | count | qids |
|---|---|---|
| **age_interval_evidence_priority_gap** | **1** | **c18a7dc8** |
| temporal_endpoint_support_gap | 1 | gpt4_93159ced_abs |
| event_cluster_interval_shape_gap | 1 | b46e15ed |
| computation_high_risk | 1 | gpt4_ab202e7f |
| evidence_present_computation_missing | 1 | gpt4_d6585ce8 |
| gold_or_input_limitation | 3 | 1c0ddc50, b6025781, d6233ab6 |

Two existing-path narrow-deterministic candidates now in
scope: `c18a7dc8` (age_interval evidence priority) and
`gpt4_93159ced_abs` (temporal endpoint support gate). Both
are integration / priority-rule fixes on existing skills,
not new skill design. Both warrant a read-only audit before
implementation.

## Decision

- **LSA-2 v1 wording revised**: the conclusion "LME-S narrow
  deterministic optimization is converged" is too strong.
  Convergence holds for **new narrow helpers**, but
  **existing-path regressions exist** on at least 2 of 8
  remaining fails (was claimed as 1 after AAS-1; correctly 2
  after the AAS-1 retraction).
- **No code change in this log**. Each existing-path issue
  needs its own scoped audit before any commit.
- **Two follow-up workstream proposals (revised 2026-05-26
  after AAS-1 retraction)**:
  1. **PRIORITY 1 (a)**: `AAS-2 — age_interval evidence
     priority audit`. Live-probe c18a7dc8 in the audit
     sandbox: capture what `_find_event_via_trinity`
     returns, whether `b_content` becomes non-empty with
     `age_at_event=None`, and whether reordering to prefer
     explicit `at the age of N` evidence (run store-scan
     before semantic escalation, or unconditionally when
     escalation returns age=None) rescues c18a7dc8 without
     regressing other older/younger qids. Read-only first.
  2. **PRIORITY 1 (b)**: `TESG-1 — temporal endpoint
     support gate audit`. Classify "how long ... before/
     after/until Y" samples into endpoint-occurred /
     endpoint-not-occurred / evidence-insufficient. Confirm
     a support-aware commit gate (mirroring V8.2.2a
     role-mismatch guard) blocks `gpt4_93159ced_abs`
     over-commit without breaking legitimate duration
     questions. Read-only first.
  3. **DEFER**: `b46e15ed event_cluster_interval`. Pre-audit
     needed to determine if "elapsed-since-cluster" shape
     recurs in more than one qid; if one-off, don't extend.

Both 1(a) and 1(b) should be e2e-validated independently
when their audits conclude — must not be packaged into one
PR for joint validation (different layers, different
positive cases, different blast radii).

Each warrants its own go-ahead. None auto-started for
implementation.

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
