# CQ-4 v2 — Nate A/B/C with Honest Setup — Close-out

**Date**: 2026-05-25
**Author**: Claude Code
**Status**: CQ-4 v2 closed. Candidate-rendering direction
**not** salvageable for Nate, but the right reason is not the
v1 close-out's reason; LLM has informed semantic preference for
the LOTR signal over the dragon-metadata signal.

---

## What v2 Fixed vs v1

User audit on 2026-05-25 (post CQ-4 v1) flagged three P1 bugs:

1. **Variant C never injected `dragon`.** v1 extracted top_k=5
   first then filtered topic_keyword — `dragon` (originally
   rank 15 in default sort) was already gone.
2. **A/B/C did NOT hold retrieved memories fixed.** Runner
   wiped sandbox/data on each invocation; "shared sandbox"
   was nominal.
3. **`evidence_section` wasn't recorded.** Couldn't verify
   what the LLM actually saw.

v2 fixes (commits `7eccbe7`, `3dd8af4`):

- `mind.py::run_evidence_candidates`: variant C extracts
  top_k=200 first, filters `relation=="topic_keyword"`, renders
  ALL filtered candidates (no truncate).
- `run_locomo_mem0.py`: `--reuse-sandbox` flag; preserves
  sandbox/data and pre-populates ingested-domain set from
  sqlite so subsequent runs skip the ingest LLM entirely.
- `run_locomo_mem0.py`: per_query record now includes
  `evidence_section[:2000]` for audit.

Wrapper `cq4_nate_abc.sh` rewritten as v2: first run (A run 1)
does fresh ingest, all 8 subsequent runs use `--reuse-sandbox`.

## Results

```
variant   pass   dragon_in_evidence (audit)   avg_elapsed
A         1/3    0/3                          (uses default top-5)
B         0/3    0/3                          (no candidate block)
C         0/3    0/3 (saved-truncate bug)     (full topic-keyword set)
```

**Audit caveat** (post-hoc): the `dragon_in_evidence` column
counts hits in the saved `evidence_section[:2000]` slice. For
variant C, the *actually-rendered* block was ~3500 chars with
15 topic_keyword candidates and `dragon` at **rank 12** — the
[:2000] slice truncated it out of the saved record. The LLM
saw `dragon`; the audit metric saw a falsely-truncated view.
Verified by re-extracting candidates against the same
sandbox/domain: dragon ranks 12/15 of topic_keyword
candidates under TOP_K=200 retrieve.

So C did inject dragon to the LLM, just not in the audit
snippet.

## What the LLM Actually Said in Variant C

All 3 C runs committed to **"Lord of the Rings trilogy"**.
Run 2 was especially explicit:

> "No conflicting newer favorite mentioned later — the later
>  recommendations (space opera, **dragon fantasy**) are just
>  recommendations, not declared as 'favorite.'"
>
> ANSWER: Nate's favorite book series is *The Lord of the
>  Rings* trilogy, an epic fantasy about a quest to destroy a
>  powerful ring, featuring battles, magic, and intricate
>  world-building.

The LLM:
1. **Saw `dragon`** in the candidate list.
2. **Saw LOTR** in the retrieved memories ("greatest trilogy
   of all time", "one of my faves" — explicit, in-dialogue).
3. **Explicitly down-weighted dragon** as "recommendation, not
   favorite" and committed to LOTR.

This is informed semantic reasoning, not the LLM ignoring the
candidate block. Gold = "dragons" originates from D9:14's
image-query metadata `[Sharing image — query: fantasy novels
dragon cover series.]` paired with the bare "I love this
series" — the gold treats the image keyword as the answer.
The LLM does not.

## Implication for the Direction

The CQ-4 v1 close-out claimed "LLM is not adopting candidate
hints even when explicit". CQ-4 v2 shows that was wrong: when
candidate dragon IS in the block (variant C), the LLM
acknowledges it but performs the comparison against other
retrieved evidence (LOTR direct mentions) and chooses
according to its own semantic weighting. The LLM is reading
the candidate block; it's just exercising judgment over
multiple signals in the retrieved set.

Three things follow:

1. **CQ-4 candidate-rendering direction is closed for Nate**,
   but for a different reason than v1 claimed: it's not
   "LLM ignores candidates", it's "LLM's semantic weighting
   correctly prefers the LOTR signal that's also in the
   retrieved memories". A stronger inject (e.g., "ANSWER MUST
   be dragons") would override the LLM judgment, but that's
   hard-pinning the gold token — explicitly disallowed by
   the project's narrow-helper rules.
2. **A 1/3 PASS** confirms Nate is **stochastic ~30-40%**, not
   stable FAIL. The earlier "stable FAIL" classification was
   based on too-small samples (1-2 runs per condition
   throughout LCR-1 and LCR-3). c3_Nate should be
   re-classified as "rotating" — the same bucket as
   c1_Gina, c6_date.
3. **Gold-quality concern**: gold "dragons" relies on
   privileging image-query metadata over the strongest
   in-dialogue signal (LOTR being called "greatest trilogy
   of all time"). This is a benchmark-design preference, not
   an obviously-correct answer. Similar to c5_Voyageurs:
   the gold expects extraction from a channel the LLM
   doesn't naturally weight as primary.

## Decision

- **CQ-4 v2 closed. Candidate-block direction NOT salvageable
  for Nate** (under deterministic, non-gold-pinning rules).
- **Reclassify c3_Nate** from "stable FAIL" to "rotating".
  Update the score-consolidation log + LCO Round-2 stability
  table.
- **Keep `RADIOMIND_CQ4_VARIANT` env-var hook** as a
  diagnostic switch. Default A unchanged.
- **Drop dragon_in_evidence audit metric** as misleading
  without raising the truncate cap; document the limitation
  in the audit script.

## Updated Stable-FAIL Set (after CQ-4 v2 reclassification)

```
stable PASS:  c2_b4 (Maria date), c3_94 (Tilly question),
              c4_5c (Seattle decisive)
rotating:     c1_69 (Gina tattoo), c6_9d (date),
              c3_a9 (Nate dragons)   ← MOVED FROM stable FAIL
stable FAIL:  c2_29 (financial),   c3_2656 (count gold quirk),
              c5_dac (Voyageurs),  c9_5a (Calvin goals)
```

## What This Does NOT Mean

- Does NOT mean "evidence_candidates layer is healthy". CQ-1
  showed it produces low-information `proper_noun_in_context`
  artifact slots in top-5 for most flip10 qids. That's a
  hygiene concern even if no single qid benefits from fixing
  it. Future `extractor-reform` workstream remains an option,
  audited under the same M1+M3+M4 framework.
- Does NOT mean LoCoMo is closed for optimization. c2_financial
  and c9_Calvin remain stable FAIL retrieval-recall misses;
  retrieval-bridging methodology is still the remaining
  architectural lever — also LLM-heavy, not narrow.

## Artifacts

- Per-run JSONs: `bench/end_to_end/cq4v2-nate-{A,B,C}-run{1,2,3}.json`
- Summary: `bench/end_to_end/cq4v2-nate-abc-summary.json`
- `mind.py::run_evidence_candidates` carries the
  `RADIOMIND_CQ4_VARIANT` env-var hook (default A, no
  production change).
- `run_locomo_mem0.py` carries `--reuse-sandbox` flag.

## Caveats

- 3 runs per variant remain low. The 1/3 PASS for A could be
  closer to 2/9 or 3/9 with a larger sample. The
  classification "rotating" is the most-honest reading at n=3
  per condition.
- `--reuse-sandbox` was used for runs 2-9; A run 1 was the
  only ingest. If ingest had been particularly favorable or
  unfavorable on this single seed, all 9 results inherit
  that.
- The audit-metric `dragon_in_evidence` was buggy (saved
  truncate cap of 2000 chars cut dragon out of the recorded
  view), so the metric should not be used to draw
  conclusions; check the source-of-truth (`evidence_section`
  content or live extract) when investigating.
