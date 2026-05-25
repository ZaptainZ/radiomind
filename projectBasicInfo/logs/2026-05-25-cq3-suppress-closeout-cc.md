# CQ-3 Suppress Rule — Close-out

**Date**: 2026-05-25
**Author**: Claude Code
**Status**: CQ-3 v1 rule will NOT be implemented (it suppresses
3 stable-PASS qids and does not catch Nate). The broader
"candidate-side change is dead" framing in earlier drafts of
this log was over-strong; revised below per user audit.

The only e2e-grounded action ahead is a focused A/B/C control
on Nate that varies the candidate-block content while keeping
the same retrieved memories. That control has NOT been run as
of this writing.

---

## Recap

CQ-3 proposed a structural suppress rule for
`render_evidence_candidates` to avoid injecting low-information
candidate blocks. The rule (v1):

```
suppress IFF
  top1.confidence <= 0.6
  AND
  no candidate has (confidence >= 0.7 AND source_count >= 2)
```

User gate for any new candidate-layer work:

  (a) At least one currently-FAIL polluted qid must improve in
      e2e under the change.
  (b) The suppress rule must be explainable via low-support
      signals (not qid / answer / stopword based).
  (c) Audit must run before any implementation.

The audit was extended in `cq1_candidate_quality_audit.py` with
an M4 "would suppress" column, run read-only on the sc3
sandbox.

## Audit Result

```
qid                   M1_def  M1_sim  M2_junk   M3_gen_def  M3_gen_sim  M4_suppress
c1_69a7c9bffe         Y       Y       0/5       0/5         0/5         inject
c2_29183ecb5e         .       .       0/5       0/5         0/5         SUPPRESS
c2_b4b43181aa         .       .       0/5       0/5         0/5         SUPPRESS  ← stable PASS
c3_2656e2c771         .       .       0/5       0/5         0/5         inject
c3_94f06e1a00         .       .       4/5       1/5         5/5         SUPPRESS  ← stable PASS
c3_a9fddfe69b         .       .       4/5       0/5         0/5         inject    ← polluted, NOT caught
c4_5cfba98ae8         .       .       2/5       0/5         1/5         SUPPRESS  ← stable PASS
c5_dac00a436e         .       .       3/5       0/5         0/5         inject
c6_9da9f73c2a         .       .       0/5       0/5         0/5         inject
c9_5ab522b5c7         .       .       3/5       0/5         0/5         SUPPRESS

  M4 suppress count: 5/10
```

5 qids would be suppressed under v1. Three of them are stable
PASS today: `c2_Maria`, `c3_Tilly-question`, `c4_Seattle`.
Per the design doc, this triggers the design-time STOP gate:

> If suppress fires on ANY stable-PASS qid → STOP.

That alone would close CQ-3. But the deeper architectural
analysis below shows the rule is unsalvageable for a stronger
reason than "risks stable-PASS regression": **even if we
relaxed the rule, suppress cannot improve e2e on any flip10
qid under the current pipeline.**

## Why CQ-3 v1 Specifically Won't Be Implemented

The v1 rule fails BOTH halves of its intended job:

- **Doesn't fire where it should.** The only qid we can
  identify as candidate-polluted (c3_Nate) is NOT suppressed
  by v1, because its set contains `fantasy` (topic_keyword
  conf=0.7, source_count=2) which clears the "high floor"
  predicate.
- **Fires where it might help nothing or hurt.** v1 suppresses
  three stable-PASS qids (c2_Maria, c3_Tilly-question,
  c4_Seattle).

That alone is enough to drop v1 as written.

### What we DON'T know yet (revised from earlier draft)

The earlier version of this log made two stronger claims that
the user audit correctly rejected:

1. _"Stable-PASS will be no-op under suppress."_ This is
   plausible from CQ-1 (these qids appear to pass via raw
   retrieve, not candidate hints), but it's a hypothesis
   not an e2e measurement. The right gate for suppress
   touching a stable-PASS qid is "include it in an e2e
   control", not "auto-STOP".

2. _"Suppressing Nate's candidate block is strictly worse
   because the candidate extractor is the only path that
   surfaces 'dragon' to the LLM."_ This contradicts the
   actual runner data flow: image-query metadata is
   concatenated into the retrieved memory content
   (`run_locomo_mem0.py` ~line 114), and the same
   `mem_results` is sent both to the raw answer prompt and
   to the candidate extractor. If `_extract_topics` can
   pick `dragon` out of D9:14's text, the raw answer prompt
   also has that text. Whether suppressing the noisy
   candidate block helps, hurts, or is neutral for Nate is
   an open empirical question, not a derivation.

   The genuine concern is narrower: in CQ-1 the LLM
   answer template ("If multiple candidates fit, prefer
   higher confidence and higher source_count") biases the
   model toward whatever IS in the candidate block. A
   noisy block of conversational openers may steer the
   model AWAY from the underlying D9:14 evidence. The
   directional sign is not clear without measurement.

## Implication (revised)

CQ-3 v1 is unsalvageable, but the broader claim "no
candidate-side change can produce an e2e win on this set"
is NOT established by what we've measured. To convert from
"v1 fails" to "candidate direction is closed", we need a
focused e2e A/B/C on the qid most likely to benefit
(c3_Nate), holding retrieved memories fixed and varying
only the candidate-block content.

The A/B/C is the minimum experiment to either:

- Find a controlled e2e win (which would re-open
  candidate-rendering as a workstream — though probably as
  conditional rendering rather than blanket suppress), OR
- Provide actual e2e evidence that no candidate-block
  variation moves Nate, at which point closing the
  candidate-side direction is justified.

## Decision

- **CQ-3 v1 suppress rule: NOT implemented** (fails to fire
  on the polluted case, fires on stable-PASS cases without
  any e2e justification).
- **Candidate-side direction: NOT closed.** Pending the
  CQ-4 Nate A/B/C control described below.
- **CQ-3 audit framework retained.** The M4 column in
  `cq1_candidate_quality_audit.py` is reusable for any
  future change to `evidence_candidates.py`.

## What This Does NOT Conclude

- Does NOT claim candidate injection is always harmless.
  Just that on the current flip10 set, no candidate-side
  change (re-rank or suppress) can produce an e2e win without
  also addressing the upstream retrieval-recall problem
  (c2/c9) or the candidate-text shape problem (Nate's reliance
  on image metadata being the only "dragon" source).
- Does NOT close `evidence_candidates.py` to future work. A
  refactor that addresses sentence-initial proper-noun
  over-extraction at the regex level (separate workstream)
  could still pay off, but should be audited under M1+M3+M4
  before any commit.

## Paused (unchanged)

- LME-S NumericAggregator other-class work.
- Retrieval-bridging methodology.
- Any new LoCoMo helper or skill.
- Any candidate-side IMPLEMENTATION change.

## Next Step (CQ-4): Nate candidate A/B/C control

Read-only experimental design (no source change for the
production renderer until results come back):

- Hold retrieved memories fixed (single sandbox, single
  retrieve run for the Nate question).
- Three answer-prompt variants:
  - **A** (current): candidate block as `evidence_candidates`
    produces today.
  - **B** (suppress): no candidate block at all.
  - **C** (topic-only): render only candidates with
    `relation == "topic_keyword"`. This is structural — no
    new extractor, no hardcoded `dragon`.
- Run each variant on Nate multiple times (≥3 to control
  for LLM seed noise).
- Decision rule:
  - If `B` or `C` shows ≥ 2 of 3 PASS on Nate while A is
    consistently FAIL → re-audit with c2_Maria /
    c3_Tilly-question / c4_Seattle / c1_Gina as regression
    controls before doing anything else.
  - If all variants stay 0/3 on Nate → candidate-side
    direction is closed for this set, and the next
    architectural choice is between retrieval-recall-
    bridging and pausing LCO entirely.

The A/B/C experiment is gated separately and not auto-
started here; it is the right next step but warrants its
own go-ahead.
