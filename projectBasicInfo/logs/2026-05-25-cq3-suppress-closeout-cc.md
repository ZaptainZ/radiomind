# CQ-3 Suppress Rule — Close-out

**Date**: 2026-05-25
**Author**: Claude Code
**Status**: Closed. **Audit gate FAILED before reaching the e2e
gate.** No implementation. Read-only audit + design doc retained.

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

## Why Suppress Cannot Win

Stable-PASS qids (c2_Maria, c3_Tilly, c4_Seattle) pass in e2e
because the raw retrieve already surfaces the gold-bearing
turn into the LLM's prompt; the candidate injection is
supplementary. Therefore suppressing them does NOT regress
e2e — but does NOT help anything either.

Stable-FAIL qids that v1 would suppress (c2_financial,
c9_Calvin):

- `c2_financial`: gold lives in D5:5 which is NOT in top-K
  retrieve at all (CQ-1 confirmed). Suppress doesn't bring
  D5:5 in; raw retrieve still feeds negative-financial
  context to the LLM. Answer stays "financial difficulties".
- `c9_Calvin`: D21:15 ("hard work and determination") is in
  store but NOT in top-30 retrieve. Suppress doesn't add it;
  raw retrieve still feeds Calvin/Dave music turns. Answer
  stays "music".

In BOTH cases the e2e failure is upstream of candidate
injection (retrieval recall miss), and suppress simply
removes a hint that wasn't useful anyway. **Zero net e2e
movement** under any honest accounting.

The qid that genuinely IS polluted by noisy candidates,
`c3_a9fddfe69b` (Nate dragons), is NOT caught by v1 because
its candidate set contains `fantasy` (topic_keyword conf=0.7,
source_count=2) which clears the "high floor" predicate. v1
correctly identifies Nate's candidates as
having a high-floor signal and stays out of the way.

Even if a v2 suppress rule were tuned tighter so it WOULD
fire on Nate, the e2e outcome wouldn't improve: the literal
"dragon" token only enters the system via image-query
metadata attached to D9:14. Suppressing the candidate block
removes the only path that surfaces "dragon" to the LLM at
all. So the suppress direction is strictly worse than
inject-with-noise for Nate.

## Implication

The "suppress when candidate set is structurally weak"
hypothesis is sound in principle but the current `flip10` /
LoCoMo pipeline doesn't have a qid where it can produce an
e2e win:

- Stable-PASS doesn't need the candidate block → suppress is
  no-op.
- Stable-FAIL polluted by candidates (only Nate) needs the
  candidate block (image-metadata is the answer source) →
  suppress hurts.
- Stable-FAIL with retrieval recall miss (c2, c9) needs a
  retrieval-side fix, not a candidate-side fix.

**Gate (a) cannot be met by any suppress rule on this set.**

## Decision

**No implementation.** CQ-3 design doc + audit + this close-
out retained as the architectural record. The reusable
`cq1_candidate_quality_audit.py` framework keeps the M4
column; can be re-run on any future change to
`evidence_candidates.py` to monitor suppress behavior.

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
- Any candidate-side change.

The current state is "no LCO-driven RadioMind change is
on the table". If continuing optimization, the architectural
choice is between:

  - A `retrieval-recall-bridging` workstream targeting the
    c2/c9 pattern (gold-in-store but not in top-K). Read-only
    audit first.
  - Pausing LCO entirely and returning to a different
    component of RadioMind.

Neither is auto-started.
