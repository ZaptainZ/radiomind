# OrderedEventList-1g — 1f Pipeline Re-Smoke

**Date**: 2026-06-01
**Author**: Claude Code
**Status**: Single-qid LLM smoke complete. No source change. Reused the
`gpt4_7abb270c` sandbox from 1e; no judge, no benchmark.

---

## Goal

Validate whether the 1f extraction pipeline

`FACT enumeration → relevance filter → chunked extraction → merge/dedup → sort`

fixes the 1e failure mode on the hardest museum ordering qid.

## Setup

- qid: `gpt4_7abb270c`
- question: `What is the order of the six museums I visited from earliest to latest?`
- gold:
  `Science Museum, Museum of Contemporary Art, Metropolitan Museum of Art, Museum of History, Modern Art Museum, Natural History Museum`
- sandbox: `/tmp/rm-sandbox-oel-1e-gpt4_7abb270c`
- re-ingest: no (sandbox reused)
- judge: no
- benchmark: no

## Result

| metric | value |
|---|---|
| FACT entries | 467 |
| filtered entries | 43 |
| chunks | 5 |
| raw extracted | 10 |
| merged | 6 |
| gold coverage | 5/6 |
| exact order == gold | false |

Rendered answer:

`Science Museum's "Space Exploration" exhibition, Museum of Contemporary Art, Metropolitan Museum of Art, Museum of History, Modern Art Museum, Richard Wagner Museum, Natural History Museum, Children's Museum`

Anchors:

1. `Science Museum's "Space Exploration" exhibition` — 2023-01-15
2. `Museum of Contemporary Art` — 2023-01-22
3. `Metropolitan Museum of Art` — 2023-02-10
4. `Museum of History` — 2023-02-15
5. `Modern Art Museum` — 2023-02-20
6. `Richard Wagner Museum` — 2023-02-24
7. `Natural History Museum` — 2023-03-04
8. `Children's Museum` — 2023-03-04

## Interpretation

1f fixed the main mechanics:

- 1e all-FACT extraction: 467 facts → 0 instances.
- 1e filtered single-pass extraction: focused set → 3/6.
- 1g 1f pipeline: filtered + chunked + merge → essentially all relevant
  museum events surfaced, chronologically ordered.

The remaining failure is not routing, FACT coverage, or sorting. It is
extraction precision:

1. **Name canonicalization gap.** The first item is over-specific:
   `Science Museum's "Space Exploration" exhibition` instead of
   `Science Museum`.
2. **Over-extraction / cardinality gap.** The question explicitly asks for
   `six museums`, but extraction emitted extras (`Richard Wagner Museum`,
   `Children's Museum`) in addition to the six intended gold items.

The events' relative time order is sensible: 2023-01-15 → 2023-01-22 →
2023-02-10 → 2023-02-15 → 2023-02-20 → 2023-02-24 → 2023-03-04.
So the skill's sort step works after extraction.

## Decision

OrderedEventList is now mechanically viable but not clean enough for a
commit-closure. The capability can route, enumerate, filter, chunk, merge,
and sort; exact gold matching is blocked by item canonicalization and
question-cardinality selection.

Two possible next steps:

1. **Stop here**: leave OrderedEventList as routed + recall-complete +
   sorted, with extraction precision explicitly marked as future work. This
   is reasonable for a roughly 7-8 qid cohort because the remaining work is
   model-extraction quality, not deterministic infrastructure.
2. **Open 1h**: add deterministic name canonicalization and cardinality-aware
   selection (question says six → choose six likely visit entities). Then
   re-smoke this same qid. This is precision tuning, not a core routing fix.

Do **not** add list-ordering commit-closure yet. A closure is only safe once
the skill consistently produces a clean ordered list.

## Artifacts

- Script: `/tmp/oel_1g_smoke.py`
- Output: `/tmp/oel_1g_out.txt`

