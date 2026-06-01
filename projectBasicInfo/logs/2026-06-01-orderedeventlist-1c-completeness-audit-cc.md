# OrderedEventList-1c — Completeness Audit (read-only)

**Date**: 2026-06-01
**Author**: Claude Code
**Status**: Read-only audit. No code change. **Headline: the 1b parser fix was
necessary but far from sufficient — post-1b, `ListOrderingSkill` STILL cannot
answer the cohort, for two binding reasons, the larger being that the skill is
unreachable (routing-dead) on the LME path.** Verified deterministically.

---

## Gap buckets (post-1b)

### (A) Routing / triggering — **DEAD, binding constraint** *(verified)*
The skill never executes for ordering questions on the LME runner path:
- The runner's ONLY entry points into the skill registry are
  `mind.run_temporal_precision(...)` (`run_longmemeval_mem0.py:514`) and
  `mind.run_open_domain_specific(...)` (`:521`). No `try_resolve`, no direct
  `list_ordering` call (grep-confirmed).
- Those two wrappers fire only on `wants=="date"` and `wants=="inference"`
  respectively (`core/mind.py` `run_temporal_precision`/`run_open_domain_specific`).
- Ordering questions classify as **non-temporal / non-inference**
  (`detail` or `lookup` depending on exact wording): verified
  `_TEMPORAL_RE.search("What is the order of the six museums…") → False` and
  `_OPEN_DOMAIN_RE.search(…) → False`, so the production `date` /
  `inference` wrappers do not call `answer_hint`.
- The LLM rescue can't help: `_TRINITY_UPGRADE_TARGETS =
  ('count','date','inference','detail','preference')` (`attention.py:415`) —
  **there is no `wants` value for ordering/list**. Best case it upgrades to
  `count` (→ cardinality, not ordering).
→ `answer_hint` / `try_resolve_soft` is never reached, so
`ListOrderingSkill.resolve` never runs. The skill is dead code on this path.
(Note: `age_interval`/`event_interval` ARE reachable because their questions
classify as `wants=="date"` via `run_temporal_precision`; ordering is the
wants-class the router lacks.)

### (B) Input window / FACT enumeration — **MISSING, the crux** *(verified)*
`resolve` operates only on the passed-in top-k `memories`, capped to the first
30 (`list_ordering.py:49,57` `memories[:max_memories]`, `max_memories=30`). It
**never** calls `list_by_domain(... FACT ...)` (grep-confirmed: absent in
`list_ordering.py`; present in `event_interval.py`/`age_interval.py`). Gold
answers are 3-6 needles across ~50 sessions; semantic top-k (then `[:30]`)
cannot recover all needles by construction. `Database.list_by_domain(domain,
FACT, limit=500)` is the deterministic full-enumeration route the other skills
use; this one doesn't.

### (D) Dedup — **MISSING** *(audit, code-cited)*
After extraction `resolve` parses dates, sorts, and `", ".join(names)` with no
name-normalization/set-collapse (`list_ordering.py` sort+join). The same event
mentioned across sessions appears multiple times in an N-item ordered gold —
directly corrupting the answer. The exhaustive-coverage extraction stance makes
duplicates more likely.

### (F) Final commit / answer-wiring — **HINT-ONLY, no commit-closure** *(audit, code-cited)*
The result reaches the answer only via `SkillResult.prefix()` →
`"STRUCTURED SKILL (…): trust this unless retrieval explicitly contradicts."`
prepended to the answer-LLM prompt (`skills/base.py:16-24`). The answer-LLM can
silently drop/reorder items — the exact trust-gap that age & cashback needed a
commit-closure for. The runner wires only the age and cashback closures
(`run_longmemeval_mem0.py:830-853`); **there is no `maybe_list_ordering_commit_closure`.**

### (C) Item-extraction caps — **secondary** *(audit, code-cited)*
Each memory is sliced `content[:300]` and the memory list `[:30]` before the
Trinity `{name,date}` extraction — both drop needles; relax once (B) makes the
input the full FACT layer.

### (E) Date attribution — **parser fixed (1b), residual risk** *(audit)*
Parsing now works. Residual: when a turn narrates a PAST event whose real date
differs from `session_date`, ordering correctness depends on the LLM picking
the in-text date; no deterministic guard → a wrong-order risk, lower priority.

---

## Prioritized gaps (binding first)
1. **(A) routing — binding.** Skill is unreachable; until fixed, B-F are
   unobservable. *Fix first.*
2. **(B) FACT enumeration — crux.** Caps recall regardless of routing.
3. **(D) dedup — cheap, high payoff** once enumeration surfaces repeats.
4. **(F) commit-closure — trust-closure parity** with age/cashback.
5. **(C) extraction caps** — relax after (B).
6. **(E) past-event date attribution** — residual, no deterministic guard.

## Recommended next slice — OrderedEventList-1d (A+B together)
A and B are each worthless without the other, so do them as one slice:
- **A (routing):** give ordering a deterministic entry point that does NOT
  depend on the missing `wants` class. Lowest-risk concrete option per the
  audit: a `mind.run_list_ordering(...)` runner section (mirroring
  `run_temporal_precision`) gated on the skill's own trigger
  (`_TRIGGER_RE`/`_TRIGGER_RE_2`, `list_ordering.py:25-33`), bypassing the
  attention `wants` gate. (Decide later whether to instead add an `"order"`
  wants-class to the router — bigger blast radius.)
- **B (completeness):** inside `resolve`, when `context["mind"]._store` is
  available, enumerate `list_by_domain(domain, FACT, limit=500)` (copy
  `event_interval`'s pattern) instead of the top-k `memories[:30]`.
- Verify on ONE cohort qid (e.g. `gpt4_7abb270c`, 6 museums) — this is where an
  ingest+LLM smoke is finally warranted (item extraction is a Trinity LLM call,
  so true recall can only be measured with the model). Gate it like the
  closures: deterministic checks first, ingest smoke when wanted.

Defer (D) one-line dedup, (F) a `maybe_list_ordering_commit_closure` mirroring
the age closure, and (E) to a follow-up once A+B surface the full candidate set.

## Verified vs audit-sourced
- **Verified by me (deterministic):** runner's only registry entry points;
  ordering question → neither date nor inference gating regex matches;
  `_TRINITY_UPGRADE_TARGETS` has no ordering class; `resolve` never calls
  `list_by_domain` and caps `memories[:30]`.
- **Audit-sourced (code-cited, not independently re-run):** dedup absence,
  `content[:300]` cap, hint-only wiring / no commit-closure, date-attribution
  residual. High confidence (all are static code facts), flagged for honesty.

## Files inspected (read-only)
- `src/radiomind/skills/list_ordering.py`, `skills/registry.py`,
  `skills/base.py`, `skills/event_interval.py`
- `src/radiomind/core/attention.py`, `core/mind.py`
- `bench/end_to_end/run_longmemeval_mem0.py`
