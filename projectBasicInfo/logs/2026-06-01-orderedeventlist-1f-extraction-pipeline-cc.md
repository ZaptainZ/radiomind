# OrderedEventList-1f — extraction pipeline (filter → chunk → merge)

**Date**: 2026-06-01
**Author**: Claude Code
**Status**: Mechanics done + deterministic tests green. Implements the
pipeline the 1e smoke showed is needed:
`FACT enumeration → relevance filter → chunked extraction → merge/dedup → sort`.
NO LLM smoke yet (per the agreed order: deterministic mechanics first; re-run
the single-qid smoke only once these are green — which they now are).

---

## Why (1e findings)
1e proved 1d-A (routing) and 1d-B (FACT enumeration) work, but:
- feeding ALL 467 facts to one extractor → **0 instances** (collapse);
- a focused subset still under-extracts with a single pass (42 facts → 3/6).
So the fix is not "more enumeration" — it is filter + chunk + merge.

## Changes (src/radiomind/skills/list_ordering.py — rewrite of the pipeline)
- `_mem_fields(m)`: unify SearchResult / dict / bare MemoryEntry → (date, content).
- `_relevance_tokens` + `_relevant_facts(candidates, noun)`: **deterministic**
  relevance filter — keep facts whose text contains an entity token, with
  singular+plural normalization (so "museums" also matches "Science Museum").
  Returns all candidates when no usable token. (Replaces the 1d "feed all
  facts" that collapsed extraction.)
- `_chunks(seq, size=10)` + `_extract_chunk(...)` (one Trinity `debate` over a
  small chunk) + `_collect_instances_via_llm(...)` now **chunks** the
  candidates and concatenates per-chunk instances (a single pass over a large
  set under-recovers). `content[:300]` relaxed to `[:400]`.
- `_norm_name` + `_merge_dedup(instances)`: collapse repeated mentions of the
  same item (normalized name), keeping the earliest parseable date — this is
  where (D) dedup folds in.
- `resolve`: enumerate FACT → `_relevant_facts` → `_collect_instances_via_llm`
  (chunked) → `_merge_dedup` → parse/sort/render. (F commit-closure still NOT
  added — the skill must first reliably produce a list.)

## Verification (deterministic, no LLM/ingest)
`tests/test_list_ordering_routing.py` (8, updated + new):
- resolve: FACT enumeration (limit 500) → filtered facts reach extraction →
  out-of-order input rendered in date order; no-store fallback to memories.
- routing: `run_list_ordering` "" on non-ordering Q, STRUCTURED SKILL hint on
  ordering Q.
- **1f mechanics**: `_relevant_facts` (singular+plural, drops irrelevant);
  `_chunks` sizing; `_collect_instances_via_llm` extracts EVERY chunk
  (monkeypatched `_extract_chunk`, asserts chunk sizes [10,10,5]);
  `_merge_dedup` collapses duplicates and keeps the earliest date.
The Trinity extraction is monkeypatched throughout — pure mechanics only.
Full regression pack: **13 categories ALL PASS** (`skill:list-ordering` now 8).

## Next — OrderedEventList-1g (authorized re-smoke)
Re-run the single-qid smoke on `gpt4_7abb270c` (sandbox, no judge/benchmark)
with the 1f pipeline live, and measure: does filter → chunk → merge now
recover **6/6 in correct order** (vs 1e's 0 on all-facts / 3/6 on a single
filtered pass)? This is the viability gate for the whole line:
- 6/6 (or close) → finish with (F) a list_ordering commit-closure for
  trust-closure parity, then it's done;
- still well short → reconsider whether the ~8-qid cohort is worth more.
Needs the model (extraction is a Trinity call); gated on explicit go.

## Files
- `src/radiomind/skills/list_ordering.py` (pipeline rewrite)
- `tests/test_list_ordering_routing.py` (updated + 1f mechanics tests)
