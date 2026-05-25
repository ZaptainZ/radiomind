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
**Layer**: **existing candidate-layer ranking quality issue**.

**REVISED FINDING (2026-05-25 user re-audit)**: the first read of
this qid placed the failure at commit layer because "dragon"
isn't in the human-dialogue portion of D9:14. That's accurate
about the text channel, but the runner intentionally
concatenates image-query metadata into the ingested turn text
(`run_locomo_mem0.py` line ~117), so "dragon" IS present in
D9:14 as ingested.

`evidence_candidates.py::_extract_topics` does recognize
`dragons?` as a `topic_keyword`. Replaying the extract on the
top-30 retrieve for this question shows the candidate IS
generated — it just lands at **rank 15**:

```
qtype: what_about
[ 1] 'Sharing'       rel=series_or_entity_name  src_count=12 conf=0.5
[ 2] 'Yeah'          rel=series_or_entity_name  src_count= 3 conf=0.5
[ 3] 'Joanna'        rel=series_or_entity_name  src_count= 3 conf=0.5
[ 4] 'Hey Joanna'    rel=series_or_entity_name  src_count= 3 conf=0.5
[ 5] 'fantasy'       rel=topic_keyword          src_count= 2 conf=0.7
[ 6] 'cover'         rel=topic_keyword          src_count= 2 conf=0.7
...
[15] 'dragon'        rel=topic_keyword          src_count= 1 conf=0.7   ← GOLD
```

The render injects only top-5 into the prompt, so the LLM never
sees "dragon" as a candidate. The 4 displaced slots are all
generic conversational openers / speaker names — `"Sharing"`
comes from the `[Sharing image — ...]` metadata prefix that
shows up in 12 different turns, dominating `source_count`. The
sort key is `(source_count desc, confidence desc)`
(`evidence_candidates.py:421`), so high-frequency artifact
tokens systematically displace low-frequency-but-direct
answer tokens.

**This is a deterministic existing-layer ranking/hygiene
problem**, not a per-qid commit miss or a dataset quirk. It
generalizes: every "what is X about" question whose answer is a
rare topic word is at risk of being displaced by artifact
proper nouns from image-share metadata, conversational
openers, and the other speaker's name.

**Verdict**: do NOT defer. This is a candidate-quality
investigation candidate. Next step is a read-only audit of
the top-5 candidate injection across all flip10 qids
(stable-PASS + stable-FAIL): which qids are dominated by
artifact tokens? Would a deterministic fix (stopword
expansion + topic_keyword priority + image-metadata prefix
filter) lift c3_Nate without unseating the stable-PASS cases
(c2_Maria, c3_Tilly, c4_Seattle)?

Only if that audit shows generalizable noise reduction with
no collateral damage does this turn into a code change.

Artifact: `bench/end_to_end/lco-audit-c3-Nate.json` (still
records D9:14 rank=4 retrieve, which is correct; the
candidate-layer detail is the new finding).

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
| c3_a9fddfe69b (Nate dragons) | existing candidate-layer ranking | no | **possibly YES** | **candidate-quality investigation candidate** (audit before implement) |
| c9_5ab522b5c7 (Calvin goals) | retrieval recall | no | NO (same family as c2) | defer |

Combined with Round-1 (c2_financial defer, c5_Voyageurs defer):

**1 of 5 stable-FAIL LoCoMo flip10 qids points at an
existing-layer improvement worth auditing** (c3_Nate →
candidate hygiene). 4 of 5 still defer.

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

Open one narrow follow-up audit (read-only) for the c3_Nate
finding before any code change:

1. Replay `extract_evidence_candidates` for every flip10 qid
   on the existing sc3 sandbox. Dump top-5 candidate
   composition per qid.
2. Count noise occurrences: how many of the 50 total top-5
   slots are conversational openers, image-share metadata
   prefixes, or the other speaker's name (i.e., what is the
   broader prevalence of the artifact pattern c3_Nate
   exposed)?
3. Simulate a stopword-expanded + topic-first re-rank.
   Verify (a) c3_Nate "dragon" enters top-5, (b)
   stable-PASS qids (c2_Maria date, c3_Tilly stuffed animal,
   c4_Seattle location) keep the candidates they currently
   rely on.

Only if step 3 shows positive net effect do we implement
candidate hygiene in `evidence_candidates.py`. The change
would be small and deterministic (stopword set + sort key
tweak) and matches the workstream norms — but it must clear
the audit gate first.

c2_financial + c9_Calvin retrieval-methodology work and
LME-S NumericAggregator other-class work remain paused
until the candidate-quality audit completes.
