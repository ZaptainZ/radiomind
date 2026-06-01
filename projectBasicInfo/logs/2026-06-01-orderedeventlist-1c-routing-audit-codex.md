# OrderedEventList-1c Routing Audit

**Date**: 2026-06-01
**Author**: Codex
**Status**: read-only follow-up audit complete. No code changes.

---

## Goal

Follow up on the 1c completeness audit before opening an implementation.
The question was whether `ListOrderingSkill` is uniquely unreachable, or
whether the production runner has a broader registered-skill routing gap.

## Production Routing Surface

The LME / LoCoMo runners do not call `mind.answer_hint(...)` directly.
They call three specialized sections:

| runner section | method | gate |
|---|---|---|
| temporal | `mind.run_temporal_precision(...)` | `analyze_with_trinity(...).wants == "date"` |
| open-domain | `mind.run_open_domain_specific(...)` | `analyze_with_trinity(...).wants == "inference"` |
| preference | `mind.run_preference_context(...)` | `aux_flags["preference_anchor"]` |

Only the first two wrappers call `answer_hint(...)`, and therefore only
those two wrappers can reach the skill registry on the production bench
path. `answer_hint(...)` itself still supports the full registry, but that
is not the path used by `bench/end_to_end/run_longmemeval_mem0.py`.

## Registered Skill Reachability

| skill | match shape | production path | verdict |
|---|---|---|---|
| `TemporalSkill` | `wants == "date"` | `run_temporal_precision` | reachable |
| `AgeIntervalSkill` | internal regex gate | reachable when query routes as date; observed age workstream confirms |
| `EventIntervalSkill` | internal regex gate | reachable for duration/between shapes that route as date |
| `ChainReasoningSkill` | internal complex temporal regex gate | reachable for its documented temporal-chain shapes because they route as date |
| `CardinalitySkill` | `wants == "count"` | registry path not used by runner, but runner has direct `get_numeric_cardinal(...)` section |
| `ListOrderingSkill` | internal order/list regex gate | no date/inference/preference/count path; natural signature is detail/lookup-like | unreachable |

Spot check with regex `analyze(...)`:

| query shape | wants |
|---|---|
| `What was the order of museums I visited from earliest to latest?` | `detail` |
| `What is the sequence of concerts from earliest to latest?` | `detail` |
| `How many months between my first charity event and my second charity event?` | `date` |
| `How many weeks had passed since I recovered ... when I went on my 10th jog?` | `date` |
| `How many instruments did I buy?` | `count` |
| `Should I attend my reunion?` | `lookup` + `preference_anchor` |

This makes the gap narrower than feared: it is not "all registered
skills outside date/inference are dead". Count and preference have
parallel runner sections; temporal-chain skills land in the date section.
The distinct missing shape is chronological list ordering, whose natural
attention bucket is `detail`/`lookup` but whose semantics require a
specialized skill.

## Design Implication

Do **not** add a broad `detail` wrapper around `answer_hint(...)`.
That would route many ordinary detail lookups through expensive trinity
and the whole registry, creating much larger blast radius than the target
problem justifies.

Do **not** add a new global `"order"` wants class as the first move either.
It would require touching the attention enum, trinity upgrade schema,
answer-shape mapping, tests, and potentially retrieval routing. That may
be worthwhile later, but it is not needed for the 1d pilot.

Lowest-risk 1d implementation:

1. Add `mind.run_list_ordering(query, retrieved_memories, domain=...)`.
2. Gate it with `ListOrderingSkill`'s existing trigger regex / `resolve`
   returning a result, not with attention `wants`.
3. Call it from the runner as a separate prefix section, analogous to the
   temporal/open/preference sections.
4. In `ListOrderingSkill.resolve`, switch from top-k-only memories to
   FACT enumeration when `mind._store` and `domain` are available.

This keeps the fix local to the known unreachable skill and avoids
changing the generic attention router.

## Remaining 1d Risk

Routing is only binding constraint A. Constraint B remains the real
retrieval/completeness issue: current `resolve(...)` uses only
`memories[:30]`, while ordered-list questions need all named instances
across roughly 50 sessions. A direct wrapper without FACT enumeration
would only make the skill callable; it would still be incomplete.

Therefore 1d should include A+B together:

- A: `run_list_ordering(...)` production entrypoint.
- B: FACT-layer enumeration inside `ListOrderingSkill`.

Then validate with deterministic unit tests first. Only after that, run
one cohort qid smoke if we want to inspect real extraction quality.

## Files Consulted

- `src/radiomind/skills/registry.py`
- `src/radiomind/skills/list_ordering.py`
- `src/radiomind/skills/event_interval.py`
- `src/radiomind/skills/chain_reasoning.py`
- `src/radiomind/skills/cardinality.py`
- `src/radiomind/core/mind.py`
- `src/radiomind/core/attention.py`
- `bench/end_to_end/run_longmemeval_mem0.py`

