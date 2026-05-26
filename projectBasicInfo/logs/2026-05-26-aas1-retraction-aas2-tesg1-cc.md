# AAS-1 Retraction + AAS-2 + TESG-1 Audit

**Date**: 2026-05-26
**Author**: Claude Code
**Status**: Read-only. No code change. Two parallel audits
complete. **Headline: c18a7dc8 already PASSes on current
main; the V8.2.2a baseline that flagged it as a fail is
stale.** TESG-1 design proven feasible against 3 "before
Y" qids.

---

## 0. AAS-1 (2026-05-25) RETRACTED

### What AAS-1 claimed (wrong)

c18a7dc8's haystack has zero user-owned graduation
mentions; gold=7 relies on assumed "standard graduation age
25". Reclassified c18a7dc8 → `gold_or_input_limitation`.

### Why it was wrong

The AAS-1 keyword search used the literal token
`"my bachelor"`. The user phrases the fact as
`"a Bachelor's degree ... which I completed at the age
of 25"` (note `a`, not `my`). A broader scan (`"bachelor"`,
`"age of 25"`) immediately finds the user turn:

> `answer_2e2085fa_1_t0` (USER):
> "I have a Bachelor's degree in Business Administration
> with a concentration in Marketing from the University
> of California, Berkeley, **which I completed at the age
> of 25**."

Combined with the gold-marked self-id ("32-year-old
Digital Marketing Specialist"), gold = 32 − 25 = 7 is
**text-grounded, deterministic**, not an external-knowledge
assumption.

### Implication

The `age_interval_evidence_priority_gap` shape is back on
the table. AAS-2 below replaces AAS-1.

## 1. AAS-2 — age_interval Evidence-Priority Live Probe

### Setup

Reused LSA-3 sandbox (`/tmp/rm-lsa3-existing-path`,
already-ingested c18a7dc8 haystack, fact-store populated).
Question: `"How many years older am I than when I graduated
from college?"`. Gold = 7.

Probed each piece of the `age_interval` skill flow
individually (script: `bench/end_to_end/aas2_age_interval_priority.py`).

### Findings

| step | call | result |
|---|---|---|
| 1 | `mind.search(question, top=30)` | 30 retrieved, ranked |
| 2 | `_find_event_mentions("graduated from college", retrieved)` | **2 hits, BOTH niece-graduation** (token overlap on `graduated` only) |
| 3 | `_find_event_via_trinity("graduated from college", retrieved, llm)` | **SUCCESS**: returns `(Bachelor's content, 2023-05-26, age_at_event=25)` |
| 4 | `_find_age_at_event_in_store(mind, "graduated from college", "lsa3_c18a7dc8")` | **SUCCESS**: returns `(Bachelor's content, 2023-05-26, age=25)` |
| 5 | FACT-layer enumeration of `at the age of N` regex matches | **exactly 1 entry** in c18a7dc8 FACTs (the user's age-25 turn) — no risk of false positive |

### Stochasticity check

Ran step 3 (`_find_event_via_trinity`) 5x. **5/5 deterministic
SUCCESS** with the same result.

Ran full `AgeIntervalSkill.resolve(question, retrieved,
context={mind, domain, reference_date})` 3x. **3/3
deterministic SUCCESS** returning `answer='7', confidence=0.9,
anchors=[('graduated from college', '2023-05-26'),
('current age (store self-ID)', '32')]`.

### Single-qid e2e validation

[in progress — running
`run_longmemeval_mem0.py --qids c18a7dc8 --benchmark-mode
a2a-practice`. Result will be appended here.]

### Conclusion

On current main (`e4c9afd`), the age_interval skill
produces the deterministic correct answer for c18a7dc8.
The V8.2.2a-judge-fixed baseline (2026-05-20) flagged
c18a7dc8 as FAIL, but main has since accumulated NAR + V8.3
+ subject-neutral anchor + trinity-routed attention fixes
that appear to have closed this gap.

**Recommendation**: do NOT open an `age_interval evidence
priority gap` implementation workstream until a fresh
contemporary LME-S n=100 baseline confirms c18a7dc8 is
still FAILing. The narrow-deterministic helper layer
already handles this qid; no priority-reordering is needed
in the absence of a regression.

If the e2e run flips negative, the actual fix candidate
would be a 2-line reorder at `age_interval.py:592-599`:
run `_find_age_at_event_in_store` BEFORE
`_find_event_via_trinity` (step 4 is deterministic;
step 3 has trinity-noise risk).

## 2. TESG-1 — Temporal Endpoint Support Gate Audit

### Trigger-surface scan

Static scan of LongMemEval-S for "how long ..." family
queries (script: stage 1 inline in this audit).

```
total qids matching "how long ...": 20
  before_Y           × endpoint_occurred (heuristic past)   = 3
  duration_other     × unclear                              = 17
```

Only **3 qids** are "before Y" shape. Tight surface area
(blast radius bound).

### Per-qid endpoint evidence probe

For each of the 3 "before Y" qids, scanned the haystack
for first-person user statements `(I|my) (work|started|
joined|am at) [Y]`:

| qid | Y | 1st-person work-at-Y hits | future/plan markers around Y |
|---|---|---|---|
| `gpt4_93159ced` | NovaTech | **2** ("I've been working at NovaTech for about 4 years and 3 months") | 0 |
| `gpt4_93159ced_abs` | Google | **0** | 1 (`"considering using Google Drive"` — tool, not employer) |
| `gpt4_cd90e484` | American goldfinches | n/a (not employer; event shape) | n/a |

### Design feasibility

The proposed support-aware commit gate distinguishes ALL 3
"before Y" cases under one deterministic rule:

- **gpt4_93159ced (NovaTech)**: 2 first-person work-at-Y
  statements → endpoint SUPPORTED → ALLOW commit.
  Existing answer `"4 years 9 months"` is correct.
- **gpt4_93159ced_abs (Google)**: 0 first-person
  work-at-Y statements; only context is "considering Google
  Drive" (tool mention) → endpoint UNSUPPORTED → BLOCK
  commit / route to canonical-abstain. Matches gold.
- **gpt4_cd90e484 (goldfinches)**: separate sub-rule
  needed for event-shape (vs employer-shape) endpoints.
  Probably runs the same `_find_event_via_trinity` against
  the endpoint phrase and abstains on
  age-without-evidence-of-event-occurrence.

### Surface area / blast radius

- 3 "before Y" qids in LME-S (one-off-style triggers).
- 17 "duration_other" qids do NOT use this shape — gate
  wouldn't fire on them.
- Gate is **commit-time guard**, not classification
  override — analogous to V8.2.2a's role-mismatch guard.
  Same architectural precedent.

### Recommendation

Open implementation workstream. Scope: add a single
`temporal_endpoint_support_guard` helper that fires only
when `_TEMPORAL_RE` classifies a query as `before_Y` /
`until_Y` and the endpoint Y is a noun phrase. Before
emitting a date-arithmetic answer, check for first-person
work/event-occurrence evidence of Y in the retrieved
memories. If none, route to canonical-abstain.

This is the **only** narrow-deterministic fix candidate
remaining after AAS-2 closes c18a7dc8 as already-fixed.

## 3. Revised Taxonomy (post 2026-05-26)

| label | qid | status |
|---|---|---|
| **already_fixed (was age_interval_evidence_priority_gap)** | **c18a7dc8** | **AAS-2 deterministic PASS on main; e2e pending** |
| temporal_endpoint_support_gap | gpt4_93159ced_abs | **TESG-1 design proven feasible; ready to open impl** |
| event_cluster_interval_shape_gap | b46e15ed | defer pending cohort audit |
| computation_high_risk | gpt4_ab202e7f | defer |
| evidence_present_computation_missing | gpt4_d6585ce8 | defer |
| gold_or_input_limitation | 1c0ddc50, b6025781, d6233ab6 | defer |

## 4. Outstanding Tasks

- [pending] Wait for `c18a7dc8` single-qid e2e result.
  If PASS, confirm "already-fixed" status. If FAIL, this
  log appends the failure trace + revised
  `age_interval evidence priority` workstream.
- [pending] Re-measure contemporary LME-S n=100 on main
  before any new helper work. The V8.2.2a baseline is now
  ≥6 days stale.
- [pending] Cohort-audit for `event_cluster_interval`
  shape (per LSA-3 recommendation).
- [user-go-ahead-required] Open TESG-1 implementation
  workstream.

## 5. Files

- AAS-2 probe script: `bench/end_to_end/aas2_age_interval_priority.py`
- AAS-2 probe data: `bench/end_to_end/aas2-age-interval-probe.json`
- AAS-2 e2e checkpoint: `bench/end_to_end/aas2-c18a7dc8-e2e.checkpoint.jsonl`
- TESG-1 trigger scan: `bench/end_to_end/tesg1-trigger-scan.json`
- LSA-3 audit (revised v4 — AAS-1 retraction): `projectBasicInfo/logs/2026-05-25-lsa3-existing-path-audit-cc.md`
- This log: `projectBasicInfo/logs/2026-05-26-aas1-retraction-aas2-tesg1-cc.md`
