# OrderedEventList-1e Follow-Up — Viability Probe

**Date**: 2026-06-01
**Author**: Codex
**Status**: read-only follow-up probe. No source change. Reused the
`gpt4_7abb270c` sandbox from 1e; no re-ingest, no judge, no benchmark.

---

## Goal

After the 1e smoke showed:

- routing works;
- FACT enumeration contains all six gold museums;
- extraction over all 467 facts returns 0 instances;
- crude plural-token filter (`"museums"`) returns only 2 instances;

the open question was whether a better singular/plural filter makes 1f
worth implementing.

## Probe

Reuse sandbox:

`/tmp/rm-sandbox-oel-1e-gpt4_7abb270c`

Filter strategy:

- derive tokens from the trigger noun `"the six museums I visited"`;
- normalize plural → singular (`museums` → `museum`);
- filter FACT entries containing `museum` or `museums`;
- run one `_collect_instances_via_llm(...)` extraction over the focused set.

## Result

| metric | value |
|---|---|
| full FACT entries | 467 |
| filtered FACT entries | 42 |
| gold coverage in filtered set | 6/6 |
| extracted instances | 3/6 |

Gold coverage:

| gold item | in filtered facts? |
|---|---|
| Science Museum | yes |
| Museum of Contemporary Art | yes |
| Metropolitan Museum of Art | yes |
| Museum of History | yes |
| Modern Art Museum | yes |
| Natural History Museum | yes |

Extracted:

1. Museum of Contemporary Art — 2023-02-20
2. Modern Art Museum — 2023-03-04
3. Metropolitan Museum of Art — 2023-03-04

Rendered order from the extracted set:

`Museum of Contemporary Art, Modern Art Museum, Metropolitan Museum of Art`

Gold:

`Science Museum, Museum of Contemporary Art, Metropolitan Museum of Art, Museum of History, Modern Art Museum, Natural History Museum`

## Interpretation

The good news: the viability of relevance filtering is confirmed.
Singular/plural filtering reduced the prompt from 467 facts to 42 facts while
keeping all six gold items. That means 1d's FACT enumeration was necessary and
the next filter can be deterministic.

The bad news: filtering alone is not enough. Even with all six gold items in
the focused set, one large extraction call only returned 3/6. The extractor is
still under-covering.

Therefore 1f should **not** be "just add a better filter". If opened, it must
include chunked or iterative extraction:

1. deterministic relevance filter after FACT enumeration;
2. split focused facts into small chunks;
3. extract `{name,date}` per chunk;
4. merge + dedup;
5. sort by date.

D (dedup) becomes part of the merge step, not a later cosmetic step. F
(commit-closure) is still premature until the skill can produce a complete
ordered list.

## Decision

OrderedEventList remains viable, but only if 1f is scoped as
**filter + chunked extraction + merge/dedup**, not a small filter-only patch.
If that feels too much for a roughly 7-8 qid cohort, stop here and leave 1d as
a routed-but-not-yet-reliable capability.

The next implementation should start with deterministic unit tests for the
filter/chunk/merge mechanics before any new ingest+LLM smoke.

## Artifacts

- Throwaway script: `/tmp/oel_1f_viability_probe.py`
- Output: `/tmp/oel_1f_viability_probe_out.txt`

