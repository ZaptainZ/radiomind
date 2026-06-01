# OrderedEventList-1d — routing (A) + FACT completeness (B)

**Date**: 2026-06-01
**Author**: Claude Code
**Status**: Done (deterministic). Makes `ListOrderingSkill` reachable on the
LME path (A) and enumeration-complete (B). Scope tightened per the 1c routing
audit: NO broad `detail` router, NO global `"order"` wants-class — a dedicated
entry gated on the skill's own trigger. Deterministic tests green + in the
regression pack. The real-extraction-quality smoke (ingest+LLM on a cohort
qid) is the authorized next step, not run here.

---

## A — dedicated routing entry
- `RadioMind.run_list_ordering(query, retrieved_memories, domain="")`
  (`core/mind.py`): bypasses the attention `wants` gate (ordering has no
  wants-class), gates purely on `list_ordering._extract_noun_from_trigger`,
  then calls `ListOrderingSkill().resolve(...)` and returns its
  `SkillResult.prefix()` (the `STRUCTURED SKILL (...)` hint) or `""`.
- Runner wiring (`run_longmemeval_mem0.py`): builds `list_ordering_section`
  next to `temporal_section`/`open_domain_section`, and prepends it to the
  answer prompt the same way. Independent of the date/inference wrappers.

## B — FACT-layer completeness
- `ListOrderingSkill.resolve` (`skills/list_ordering.py`): when
  `context["mind"]._store` + `domain` are available, enumerate the full FACT
  layer (`list_by_domain(domain, MemoryLevel.FACT, limit=500)`, copying
  event_interval/age_interval) and feed THOSE to extraction with
  `max_memories=500`, instead of the passed-in top-k `memories[:30]` (which
  structurally cannot recover 3-6 needles from ~50 sessions). Falls back to
  the top-k path when no store/domain.
- `_collect_instances_via_llm` now also accepts a bare `MemoryEntry`
  (`elif hasattr(m, "content")`) — list_by_domain returns those, which the
  old SearchResult/dict-only branch silently dropped.

## Deliberately NOT done (per 1c, deferred)
- (D) dedup, (F) a `maybe_list_ordering_commit_closure` trust-closure, (C)
  relaxing `content[:300]`, (E) past-event date attribution. These are
  follow-ups once a real cohort smoke shows whether A+B surface the full
  candidate set and where the residual errors are.
- No `detail` router change, no `"order"` wants-class (both bigger blast
  radius than the evidence supports).

## Verification (deterministic, no LLM/ingest)
`tests/test_list_ordering_routing.py` (new, 4): the Trinity extraction is
monkeypatched to canned instances so routing + FACT-enum + sort/render are
exercised without a model:
- resolve enumerates the store's FACT layer (limit 500), hands those facts to
  extraction (not the empty top-k), and renders the date-sorted list
  (`"Science Museum, Met, Modern Art Museum"` from out-of-order input).
- resolve falls back to the top-k cap (30) when no store.
- `run_list_ordering` returns `""` on a non-ordering question (gate) and a
  `STRUCTURED SKILL (list_ordering, …)` hint on an ordering question.
Added as regression-pack category `skill:list-ordering`. Full pack: **13
categories ALL PASS** (exit 0), no regression.

## Next — OrderedEventList-1e (authorized smoke)
Run ONE cohort qid through ingest+LLM to measure real extraction quality:
`diagnose_qid`/runner on `gpt4_7abb270c` (6 museums) — confirm the skill now
(a) routes, (b) sees all 6 needles via FACT enumeration, (c) extracts+orders
them. This needs the model (extraction is a Trinity call), so it is gated on
explicit go, like the closure smokes. The result decides whether (D) dedup /
(F) commit-closure are needed next.

## Files
- `src/radiomind/skills/list_ordering.py`, `src/radiomind/core/mind.py`,
  `bench/end_to_end/run_longmemeval_mem0.py`
- `tests/test_list_ordering_routing.py` (new),
  `bench/end_to_end/regression_pack.py` (+category)
