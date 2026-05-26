# AAS-1 Retraction + AAS-2 + TESG-1 Audit

**Date**: 2026-05-26
**Author**: Claude Code
**Status**: Read-only. No code change. Two parallel audits
complete. **Headlines (revised after e2e)**:

1. AAS-1 retracted — c18a7dc8 haystack DOES contain the
   user-owned `age of 25` evidence (AAS-1 keyword-search
   bug missed it).
2. AAS-2 reveals a NEW failure layer:
   `structured_skill_trust_gap` — the `age_interval`
   skill computes `7` correctly and the prefix gets
   injected with "trust this" instruction, but the
   answer-LLM (deepseek-v3.2) ignores it and abstains.
   The judge wrongly marks the abstain answer PASS for
   gold=`7`, so the V8.2.2a baseline `correct=True`
   masks the real failure.
3. TESG-1 design proven feasible against 3 "before Y"
   qids; still the cleanest narrow workstream candidate.
4. Baseline integrity caveat: `judge_abstain_acceptance_
   for_concrete_gold` inflates LME-S PASS counts;
   strict-judge re-runs needed before any "X passes
   already" conclusion.

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

### Single-qid e2e validation — RESULT

Ran `run_longmemeval_mem0.py --qids c18a7dc8
--benchmark-mode a2a-practice --answer-model deepseek-v3.2
--judge-model gpt-4o`.

- Final answer: **"The information provided is not enough."**
  (abstain).
- Gold: **"7"**.
- Judge verdict: **`correct=True`** with reasoning
  "refraining from answering due to lack of information,
  which aligns with the rules for abstention matching."

The skill PRODUCED the correct answer, the prefix was
INJECTED ("trust this unless retrieval explicitly
contradicts. Computed answer: 7"), but **the answer-LLM
ignored the prefix and abstained anyway**. The judge then
gave PASS for an abstain answer against a concrete gold,
which is wrong per LME-S rules.

This means there are **two real defects** here, neither
labeled `age_interval_evidence_priority_gap`:

1. **`structured_skill_trust_gap`**: deepseek-v3.2 (and
   possibly other answer-LLMs) ignore the
   `STRUCTURED SKILL ... trust this` prefix on this qid
   shape ("how many years older am I"). The prefix
   instruction is not strong enough OR the LLM
   over-weights "no evidence in raw memories of
   graduation date" over "structured skill says 7". The
   skill output is computed but **not committed** by the
   final answer-LLM.
2. **`judge_abstain_acceptance_for_concrete_gold`**: the
   gpt-4o judge accepted an abstain answer when gold was
   "7". This is a benchmark artifact (judge prompt rule),
   not a RadioMind code defect, but it inflates baseline
   PASS counts and masks `structured_skill_trust_gap`
   regressions.

Reproduction:

```
mind.run_temporal_precision("How many years older am I
than when I graduated from college?", retrieved, q_date,
"lsa3_c18a7dc8")  # 3/3 deterministic returns
"STRUCTURED SKILL (age_interval, conf=0.90): trust this...
- graduated from college → 2023-05-26
- current age (store self-ID) → 32
Computed answer: 7"
```

But the final answer (after the prompt template inserts
this prefix + retrieved memories) is "not enough" abstain.

### Revised recommendation

The `age_interval_evidence_priority_gap` label was
**partially wrong**: the skill ITSELF works. The actual
gap is downstream commit. Two new candidate workstreams
(both narrow, both deterministic):

- **TSI-1 (`trust_structured_skill_in_answer_LLM`)**:
  audit how the answer-LLM uses the `STRUCTURED SKILL`
  prefix. If the prefix is being silently ignored on
  >X% of qids where skill conf >= 0.85, change tactics:
  (a) post-LLM check — if skill produced a high-conf
  answer and LLM abstained, override; OR (b) stronger
  prefix wording with concrete examples of when to trust.
  Read-only first: probe what fraction of skill-firing
  qids end in LLM-abstain.
- **JAB-1 (`judge_abstain_acceptance`)**: not a code
  workstream — flag to upstream LongMemEval repo / pin
  judge prompt revision. Out of RadioMind scope but
  affects baseline measurement integrity.

The TESG-1 endpoint-support-gate work below remains
unrelated to this finding and still stands as the
primary in-scope narrow-deterministic workstream.

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

## 3. Revised Taxonomy (post 2026-05-26 AAS-2 e2e + judge-bug finding)

| label | qid | status |
|---|---|---|
| **structured_skill_trust_gap** (NEW) | **c18a7dc8** | **skill correctly outputs `7`; answer-LLM ignores STRUCTURED SKILL prefix and abstains; judge wrongly accepts abstain as PASS for gold=`7`** |
| temporal_endpoint_support_gap | gpt4_93159ced_abs | **TESG-1 design proven feasible; ready to open impl** |
| event_cluster_interval_shape_gap | b46e15ed | defer pending cohort audit |
| computation_high_risk | gpt4_ab202e7f | defer |
| evidence_present_computation_missing | gpt4_d6585ce8 | defer |
| gold_or_input_limitation | 1c0ddc50, b6025781, d6233ab6 | defer |
| **judge_abstain_acceptance_for_concrete_gold** (NEW) | benchmark-wide | flag upstream; affects baseline integrity |

## 4. Outstanding Tasks

- [done] `c18a7dc8` single-qid e2e: marked PASS by judge
  but answer was abstain — see Section 1 for the
  `structured_skill_trust_gap` finding.
- [user-go-ahead-required] Open TSI-1 read-only audit:
  audit how often answer-LLM ignores a high-conf
  STRUCTURED SKILL prefix. If the rate is meaningful,
  this is a bigger lever than TESG-1 (which only affects
  abstain-shape questions, while TSI-1 affects ANY skill
  computing a high-conf answer).
- [user-go-ahead-required] Open TESG-1 implementation
  workstream (still valid and independent).
- [user-go-ahead-required] Re-measure contemporary LME-S
  n=100 on main with **strict-judge** (re-judge runs
  ignoring the abstain-acceptance loophole) before any
  baseline conclusions. Current V8.2.2a "0.92" includes
  judge-passed abstains.
- [pending] Cohort-audit for `event_cluster_interval`
  shape (per LSA-3 recommendation).

## 5. Files

- AAS-2 probe script: `bench/end_to_end/aas2_age_interval_priority.py`
- AAS-2 probe data: `bench/end_to_end/aas2-age-interval-probe.json`
- AAS-2 e2e checkpoint: `bench/end_to_end/aas2-c18a7dc8-e2e.checkpoint.jsonl`
- TESG-1 trigger scan: `bench/end_to_end/tesg1-trigger-scan.json`
- LSA-3 audit (revised v4 — AAS-1 retraction): `projectBasicInfo/logs/2026-05-25-lsa3-existing-path-audit-cc.md`
- This log: `projectBasicInfo/logs/2026-05-26-aas1-retraction-aas2-tesg1-cc.md`
