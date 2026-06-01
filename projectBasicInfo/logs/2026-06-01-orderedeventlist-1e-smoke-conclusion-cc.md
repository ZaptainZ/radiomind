# OrderedEventList-1e — single-qid smoke conclusion

**Date**: 2026-06-01
**Author**: Claude Code
**Status**: Diagnostic only (no code change). Single qid `gpt4_7abb270c`
(6 museums), sandbox, no judge/benchmark. **Verdict: 1d's A (routing) and B
(FACT enumeration) demonstrably work, but the skill is still non-functional
end-to-end — the binding constraint has moved to (C) item extraction, and
1d-B's "feed ALL facts to extraction" is itself counterproductive.**

---

## What was run
`gpt4_7abb270c` ingested into a sandbox (467 turns / 48 sessions). Then two
probes (the second reuses the sandbox, no re-ingest):
1. routing + coverage + `resolve`;
2. extraction over ALL facts vs over a token-filtered subset.

## Findings (the three asked-for points + the new one)
1. **Routing — WORKS.** `_extract_noun_from_trigger` matched (`'the six
   museums I visited'`), so `run_list_ordering` reaches `resolve`. (1d-A good.)
2. **Coverage — WORKS.** FACT enumeration returns all 467 facts; **all 6 gold
   museums are present in the FACT layer.** The data is there. (1d-B's
   enumeration target is satisfied.)
3. **Order — FAILS.** `resolve.answer == None`, `run_list_ordering` hint empty.
   `resolve` returned None because extraction produced < 2 instances.

### The decisive new finding — extraction (C) is the binding constraint
Measured directly:
- **Extraction over all 467 FACT entries → `0` instances.** Dumping ~467×300
  chars into a single Trinity `debate` collapses extraction entirely. So
  1d-B's unconditional "use the whole FACT layer as the extractor input" does
  not just under-perform — it **breaks** extraction (worse than the old
  top-30, which at least returned something).
- **Extraction over a token-filtered subset → `2` instances** (filter token
  `"museums"` matched 22/467 facts; extracted "Natural History Museum, Modern
  Art Museum"). Filtering helps (0 → 2) but is still far from 6/6.

Caveat (honest): that filter was crude — a single **plural** token `"museums"`,
which does not match singular gold names like "Science Museum" /
"Metropolitan Museum of Art", so it likely dropped 4 museums' facts before
extraction even ran. So "2/6" is a floor from a bad filter, not the ceiling of
a good one.

## Conclusion — what 1d got right / wrong, and what's next
- **Right:** routing (A) and enumeration (B) are real and necessary; the smoke
  proves both fire and the needles exist in FACTS. The deterministic 1d tests
  were correct about the code paths.
- **Wrong / revised:** **B's "extract from ALL enumerated facts" is harmful.**
  Enumeration must be followed by a **relevance filter** down to the entity's
  candidate facts BEFORE extraction (the pattern `event_interval` already uses
  — token-overlap scan), and probably **chunked/iterative extraction** so N
  items are pulled reliably from the focused set.
- **NOT D / F yet.** Dedup and a commit-closure are premature: the skill can't
  yet produce a list at all. The next slice is **(C) extraction quality**, not
  trust-closure.

## Recommended next — OrderedEventList-1f (extraction)
1. In `resolve`, after FACT enumeration, **filter** facts to the entity's
   candidates (singular+plural / token-overlap, like `event_interval`), and
   feed only those to extraction instead of all 467. (Also revisit the
   `content[:300]` truncation for the kept facts.)
2. If a focused set still under-extracts, **chunk** extraction (extract per
   batch, merge) so all N items surface.
3. Re-run this same single-qid smoke to measure 6/6 recovery + order before
   considering D (dedup) / F (commit-closure).

The open viability question for the whole line: **can a proper relevance
filter + chunked extraction recover 6/6 in order?** If yes, OrderedEventList is
worth finishing; if even that tops out well below N, the capability may not be
worth the build for a ~8-qid cohort. 1f's first probe answers this.

## Artifacts
- Throwaway smoke scripts in `/tmp` (oel_1e_smoke.py, oel_1e_probe2.py); not
  committed. Sandbox `/tmp/rm-sandbox-oel-1e-gpt4_7abb270c` retained for 1f.
- No source change in 1e.
