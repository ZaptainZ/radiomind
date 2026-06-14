# BioLocalRetrieval-1b — FTS-only bare-install typed-facet rerank

**Date:** 2026-06-14
**Author:** Claude Code (cc)
**Scope:** Lift the bare-install FTS-only evidence-recall floor with a gated,
bounded, deterministic typed-facet rerank. **Does NOT touch the embedding path,
the reranker path, remote retrieval, consent, benchmark scoring; no LLM; no
network; no HDC.** First runtime change to the retrieval path in this campaign —
deliberately narrow and do-no-harm-gated.

## Background (from 1a)

- FTS-only recall@30 = 0.147; typed facets = 0.427; local ONNX = 0.698; HDC = no
  gain (dropped). Facets help but HARM temporal-reasoning / ordering queries →
  must be query-type gated.
- 1a's A baseline was even understated: for hard natural-language questions
  `search_fts` (AND of all terms) returns **nothing** (no single memory carries
  every term), so the live `mind.search` returns `[]`. The bare-install failure
  mode is "FTS-AND retrieves nothing", not "gold ranked low".

## Implementation

**New `src/radiomind/storage/facet_rerank.py`** (pure, deterministic, mirrors the
1a tier-B scoring so the offline probe replays the runtime logic):
- `should_rerank(query)` — gate. Enable only on a real anchor (number/amount or
  Title-Case/brand entity) AND not temporal/ordering/list/CJK. Skip reasons:
  `temporal_or_ordering` / `no_facet_anchor` / `cjk_query`. The skip regex matches
  ordering/temporal *intent* (`in what order`, `order of`, `earliest`, `latest`,
  `when`, `what date`, `how long`, `how many days|weeks|months|years`), NOT bare
  `first/last/before/after` (those wrongly killed "cashback at SaveMart last
  Thursday").
- `rerank(query, q_date, pool, max_results)` — FTS-norm + bounded facet bonus
  (num .40 / ent .30 / phrase .25 / role .08 / time .10, each capped ×3); sets
  `method="fts_facet"` on promoted results; pure (no writes to stored entries).

**Wiring in `PyramidSearch.search` (`_maybe_facet_rerank`)** — runs ONLY when:
1. `self._embedder is None and self._reranker is None` (FTS-only path), AND
2. the gate passes, AND
3. **the keyword pipeline returned NOTHING** (`fused` empty). This is the
   do-no-harm key: measurement showed that when AND-FTS already returns a full
   page (e.g. 1e043500, fused=27, gold at rank 1), widening to OR + facet rerank
   demotes the gold to rank 6. Acting only on the empty case = nothing to harm.
When it runs, it builds a WIDE candidate net with **OR** semantics
(`search_fts_or`, the AND→OR fix — AND returned 0), unions with `fused`, facet-
reranks, truncates downstream to `max_results`. Decision recorded on
`pyramid._last_facet_debug` (`used` / `reason`); promoted rows carry
`method="fts_facet"` for visibility.

`is_remote`/consent/embedder/reranker code paths are untouched.

## Verification

**Runtime do-no-harm (`biolocal_probe.py --harm-check`)** — per qid, fresh store,
`mind.search` rerank OFF vs ON, best gold rank:

| qid | type | OFF | ON | verdict |
|---|---|---|---|---|
| bb7c3b45 | multi-session | — | 11 | IMPROVE |
| 9aaed6a3 | multi-session | — | 4 | IMPROVE |
| 51a45a95 | single-session | — | 3 | IMPROVE |
| 9ee3ecd6 | multi-session | — | — | (fired, OR-pool miss) |
| 1e043500 | single-session | 1 | 1 | preserved (fts_nonempty skip) |
| e47becba / 58bf7951 | single-session | — | — | skip (no_facet_anchor) |
| b46e15ed / gpt4_d6585ce8 / c18a7dc8 / gpt4_93159ced | temporal | — | — | skip (temporal) |
| 118b2229 | single-session | — | — | skip (temporal: "how long") |
| d851d5ba | multi-session | — | — | skip (no_facet_anchor) |

**improved: 3, harmed: 0.** Every OFF="—" confirms the current FTS-AND pipeline
retrieves no gold for these anchored queries; ON recovers 3. 1e043500 (the only
qid where FTS-AND was healthy) is preserved.

- `tests/test_facet_rerank.py` — 16 tests (gate enable/skip incl. CJK; scoring
  promotes anchored low-FTS gold; runtime recovers-when-empty, does-not-disturb-
  healthy-FTS, temporal-skip, **no-rerank-when-embedder-present**). All pass.
- regression_pack ALL PASS (+ new `retrieval:facet-rerank`).
- Broad retrieval sanity (test_mind / test_iterative_search / test_e2e /
  test_community) 51 passed — no regression from the pyramid edit.

## Files changed

- `src/radiomind/storage/facet_rerank.py` (new) — gate + scoring.
- `src/radiomind/storage/pyramid.py` — `_maybe_facet_rerank` + guard after RRF.
- `tests/test_facet_rerank.py` (new) — 16 tests.
- `bench/end_to_end/biolocal_probe.py` — added `--harm-check` mode.
- `bench/end_to_end/regression_pack.py` — register `retrieval:facet-rerank`.

## Conclusion

**PASS.** FTS-only (bare-install) users get measurable recall gains (3 qids
recovered from "not retrieved at all" to top-30) with zero harm: the rerank fires
only when keyword retrieval returns nothing, only on anchored non-temporal
queries, only when no embedder/reranker is present. The local ONNX and remote
paths are byte-for-byte unchanged. HDC stays PARKED. Cloud vector remains a
convenience, not a quality necessity — 1b just raises the floor for users who skip
the local embedder. Conservative wins left on the table (gpt4_93159ced,
d851d5ba, 118b2229) are the deliberate cost of do-no-harm; revisit only with new
evidence.

See [[project_biolocal_retrieval]] (1a), [[project_managed_retrieval]],
[[project_lme_s_fail_families]].
