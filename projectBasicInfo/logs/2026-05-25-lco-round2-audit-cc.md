# LCO Round 2 — Stable-FAIL Audit (c3 count / c3 Nate / c9 Calvin)

**Date**: 2026-05-25
**Author**: Claude Code
**Type**: Read-only audit. **No code changes.** Structured
diagnostic JSONs accompany each per-qid verdict.
**Framework**: `bench/end_to_end/lco_audit.py` produces machine-
readable records (question / gold / evidence ids / top-K hits /
gold ranks) per qid.

---

## Per-qid Diagnostics

### c3_2656e2c771 — "How many of Joanna's writing have made it to the big screen?"

**Gold**: "two".
**Evidence**: D15:1, D25:2.
**Default retrieval (top-30)**: 2/2 evidence ranks — D25:2 rank 6, D15:1 rank 22.
**Layer**: **gold spec inconsistent**, NOT a RadioMind layer issue.

Reading neighbors of D25:2:

- D15:1 (Joanna): "I wrote a few bits for a screenplay that appeared on the big screen yesterday!" — event #1
- D25:2 (Joanna): "Another movie script that I contributed to was shown on the big screen last Sunday" — event #2
- **D25:4 (Joanna): "I know this is the third time it's happened"** — **explicit "third"** spoken in dataset

LLM answers "Three" across SC-3 / LCR runs. By the dataset's
own strongest assertion (D25:4 "third time"), the LLM is correct.
The benchmark's `evidence` field lists only 2 turns and the
`answer` field is "two", but the dataset text itself contains
"third". This is a **gold-spec inconsistency**, not a retrieval
or commit failure.

**Verdict**: defer; would-be intervention is gold/evidence
correction in the benchmark dataset, not RadioMind code.
Closest analogue: `370a8ff4` LME-S errata.

Artifact: `bench/end_to_end/lco-audit-c3-count.json`.

### c3_a9fddfe69b — "What is Nate's favorite book series about?"

**Gold**: "dragons".
**Evidence**: D9:14.
**Default retrieval (top-30)**: 1/1 — D9:14 at rank 4.
**Layer**: **commit / inference**.

D9:14 text: _"I love this series. It has adventures, magic, and
great characters - it's a must-read!"_ — **no "dragon" token in
human dialogue**.

The token "dragon" appears only in the ingested image-query
metadata appended to D9:14: `[Sharing image — query: fantasy
novels dragon cover series.]`. LLM in all 3 SC-3 runs reads this
hint but answers in terms of the dialogue's literal content
("adventures, magic, great characters") and does not commit to
"dragons" as the central concept.

**Verdict**: defer. A narrow rule that "prefers image-query
metadata tokens when answering 'about'-style questions" is too
niche and brittle — it would over-fire on irrelevant
attachments. Same gold-quality concern as c3_count: the
dataset's stated gold relies on image-query metadata, not the
text, which sits between architectural ceiling and dataset
quirk.

Artifact: `bench/end_to_end/lco-audit-c3-Nate.json`.

### c9_5ab522b5c7 — "What do Calvin and Dave use to reach their goals?"

**Gold**: "Hard work and determination".
**Evidence**: D21:15.
**Default retrieval (top-30)**: 0/1 — D21:15 NOT in top-30. Store
contains the literal string (3 hits across all conversations),
so the turn is ingested.
**Layer**: **retrieval recall miss** — same family as
c2_29183ecb5e financial.

Top-10 default hits: "Thanks Dave / Thanks Calvin / appreciate
support / pushing for goals" turns. The scorer (BM25/embedding)
matches "goals" and "pushing" but does not surface D21:15's
"hard work and determination" phrase. Across SC-3 runs the LLM
infers "music" from other top-K Calvin/Dave music-related
turns — a downstream consequence of D21:15 not being in the
prompt.

User flagged this as "V7 historical stable PASS → contemporary
stable FAIL". Likely cause: V7-era retrieve / rerank config or
candidate-pipeline scoring shifted enough that D21:15 dropped
out of top-K. We did NOT bisect that drift in this audit (would
require V7 HEAD re-run, expensive).

**Verdict**: defer. Same root cause as c2_financial — query
lexically anchored on "goals" doesn't bridge to "hard work and
determination" phrasing. A narrow deterministic fix is hard;
the LLM-heavy fix is the same retrieval-methodology workstream
already flagged for c2.

Artifact: `bench/end_to_end/lco-audit-c9-Calvin.json`.

---

## Round-2 Synthesis

| qid | error layer | gold-quality concern? | narrow deterministic fix? | verdict |
|---|---|---|---|---|
| c3_2656e2c771 (count) | n/a (dataset gold says "two", text says "third") | **YES** — gold-spec inconsistency | n/a | defer; errata candidate |
| c3_a9fddfe69b (Nate dragons) | commit | partial — gold relies on image-query metadata, not dialogue text | NO | defer |
| c9_5ab522b5c7 (Calvin goals) | retrieval recall | no | NO (same family as c2) | defer |

Combined with Round-1 (c2_financial defer, c5_Voyageurs defer):

**0 of 5 stable-FAIL LoCoMo flip10 qids have a narrow
deterministic fix path within current architecture.**

Breakdown by layer:

| layer | qids | comment |
|---|---|---|
| retrieval recall miss | c2_financial, c9_Calvin | needs query-side methodology (reverse-inference / lexical bridging) — LLM-heavy, not narrow |
| commit-layer / inference | c3_Nate | needs preference rule on image-query metadata — too niche |
| dataset gold spec | c3_count, c5_Voyageurs | benchmark quality issue, not RadioMind |

## Implications

1. **No new helper workstream from LCO.** None of the 5 stable-
   FAIL qids meets the "gold-evidence extractable + answer
   deterministically derivable + narrow trigger" bar.

2. **Retrieval-methodology is the load-bearing direction** if
   we want to lift c2 and c9 simultaneously. The pattern is
   "query mentions concept A, gold lives under concept B
   (reverse inference / alternative phrasing), default
   scorer doesn't bridge". A separate workstream
   (`retrieval-bridging-recall`) should treat this as a
   methodology problem, not a per-qid helper. Open as
   read-only audit first if/when prioritized.

3. **Dataset-quality concerns** for c3_count and (text-side
   for) c5_Voyageurs are real but not in RadioMind's scope.
   Should be tracked separately if benchmark scoring matters
   long-term.

4. **Round-2 hit-rate (0/3) is similar to Round-1 (0/2)**.
   Total stable-FAIL stack offers no narrow-target work in
   the current text-only + narrow-deterministic frame. Time
   to either widen the frame (retrieval methodology) or
   pause LoCoMo-side optimization.

## Round 2 Diagnostic Artifacts

- `bench/end_to_end/lco_audit.py` — reusable audit framework.
- `bench/end_to_end/lco-audit-c3-count.json`
- `bench/end_to_end/lco-audit-c3-Nate.json`
- `bench/end_to_end/lco-audit-c9-Calvin.json`

Each contains: `question`, `gold_answer`, `gold_evidence_ids`,
`domain`, `default_search.top_k`, `default_search.hits[]` (rank,
turn_id, score, method, content_preview), `default_search.gold_ranks{}`.

## Recommendation

Close LCO. The combined Round-1+Round-2 verdict is "current
stable-FAIL set is genuinely beyond narrow deterministic
intervention". If continuing optimization, either:

  a) Pause LoCoMo-side work, return to LME-S where deterministic
     wins remain available (next layer would be NumericAggregator
     recall on classes other than charity_donations — e.g.,
     kitchen_items recall has known gaps from earlier audits).
  b) Open a `retrieval-bridging-recall` methodology workstream
     specifically to address the c2/c9 family. Acknowledge up
     front that the fix is LLM-heavy (query expansion /
     decomposition tuning), not narrow.

Neither is a follow-up to this audit; both are separate
workstreams that should not be auto-started.
