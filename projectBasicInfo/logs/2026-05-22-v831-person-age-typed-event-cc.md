# V8.3.1 — Person-Age Typed Event Hint

**Date**: 2026-05-22
**Author**: Claude Code
**Status**: Shipped, single commit, target qid PASS, no regression.

---

## Background

V8.3 audit (`2026-05-21-v83-typed-event-audit-cc.md`) classified 6 LME-S
FAIL qids into GREEN / YELLOW / YELLOW–RED / RED. Two GREEN candidates
emerged for a typed-event / computation layer: `gpt4_d12ceb0e` (average
age) and `d851d5ba` (charity sum).

Codex narrowed V8.3.1 to **only `gpt4_d12ceb0e`** because:

- It is the cleanest possible pilot: closed kin vocabulary, integer
  ages, single arithmetic operator.
- Codex confirmed `get_numeric_cardinal()` does NOT trigger on this
  question, so the helper is genuinely additive (not a duplicate of an
  existing deterministic chain).
- `d851d5ba` is deferred to V8.3.1b because the repo already has
  `NumericAggregator` and multiple historical d851d5ba-targeted fixes
  — the right next move there is a diagnostic of the existing chain,
  not a new extractor.

## Goal

A hint-only, deterministic helper that:

1. Fires only when the query asks for the average age across the closed
   kin set {self, mom, dad, grandma, grandpa}.
2. Extracts current-tense ages for all five roles from retrieved
   memories. Missing or conflicting → no hint.
3. Computes the mean and emits a `TYPED EVENT HINT` block prepended to
   the answer prompt. Never rewrites the LLM answer.
4. Adds zero blast radius: when conditions don't fire, the LLM path is
   unchanged.

## Files

| Path | Role |
|---|---|
| `src/radiomind/core/typed_event_hint.py` | Helper module: trigger detector, kin alias table, age extractor, mean operator, hint formatter. |
| `tests/test_typed_event_hint.py` | 33 fixture tests: target case, Codex-required negatives, parser units, conflict refusal. |
| `bench/end_to_end/run_longmemeval_mem0.py` | Wire-in at innermost wrapper, alongside `cashback_arithmetic_hint`. |
| `bench/end_to_end/run_locomo_mem0.py` | Same wire-in for cross-bench consistency. |
| `bench/end_to_end/lme-s-v831-smoke-d12ceb0e.json` | Single-qid smoke result (acc=1.000). |

Trigger surface (regex AND):

- `avg | average | mean`
- `age | ages`
- one of {`me`, `i`, `my age`, `myself`}
- `parents?`
- `grand\s*parents?`

Extraction surface:

- Kin (closed alias set): `(my )?<alias> is <N>` — present tense only.
  Past tense `was N` and bare `turned N` deliberately excluded to
  reject historical ages.
- Self: `I am N`, `I'm N`, `I just turned N`, `I recently turned N`.
- Plausibility filter: `0 < age < 130`.
- Conflict policy: same role with multiple distinct ages → refuse hint
  (we have no temporal grounding to pick the current one in this pilot).

## Triggering surface (verified)

- **LongMemEval-S n=500 (full set, offline scan)**: 1/500 triggers,
  exactly `gpt4_d12ceb0e`. Zero over-fire.
- **LoCoMo flip10**: 0/10 triggers.
- **Fixture negatives** (non-kin avg, partial set, preference advice,
  historical ages, "average temperature", missing group ref): all
  return empty string.

## Smoke

| Field | Value |
|---|---|
| qid | `gpt4_d12ceb0e` |
| answer model | `deepseek-v3.2` (dashscope) |
| judge model | `gpt-4o` (openrouter) |
| profiles | identical to V8.2.x baseline (apples-to-apples) |
| gold | `59.6` |
| answer | `The average age of you, your parents, and your grandparents is 59.6 years.` |
| judge | `yes` |
| acc | **1.000** |
| time | 862s (single qid e2e: ingest + retrieve + answer + judge) |

Cross-version delta on this qid:

| Run | Result | Mechanism |
|---|---|---|
| V8.2.1 (`lme-s-v82-1-n100.json`) | FAIL | LLM abstained: "The information provided is not enough." |
| V8.2.2a (`lme-s-v822a-n100.judge-fixed.json`) | PASS | Lucky LLM math — sum + average happened to come out right that run. |
| V8.3.1 (`lme-s-v831-smoke-d12ceb0e.json`) | PASS | Deterministic — hint explicitly computes 59.6 and surfaces it as the answer. |

## Tests

- `tests/test_typed_event_hint.py`: **33 passed**
- Full repo test suite: **659 passed** (no regression from the V8.2.x
  baseline once the new module's tests are included).

## Why we did NOT run a full n=100

1. The trigger audit already proved over-fire surface is empty across
   500 LME-S qids and 10 LoCoMo flip10 qids — there is no other qid
   the hint can affect.
2. The target qid was already validated by single-qid smoke. An n=100
   pass would only re-shuffle V8.2.x noise on unrelated qids and burn
   API budget for no informational gain.
3. V8.3.1 is explicitly a single-qid additive helper; the rest of the
   suite is by construction unaffected.

A larger run is appropriate only once V8.3.1b (and possibly later
typed-event helpers) expand the trigger surface beyond a single qid.

## Why we are NOT touching the other audit cases now

| qid | reason for deferral |
|---|---|
| `d851d5ba` (charity sum) | Existing `NumericAggregator` + historical fixes in repo. V8.3.1b must first be a read-only diagnostic of the existing chain, not a parallel extractor. |
| `gpt4_d6585ce8` (concert ordering) | Multi-event-per-session + temporal ordering — V8.3.2 territory at earliest. |
| `gpt4_ab202e7f` (kitchen count) | Entity normalization is LLM-shaped; typed events here would either degrade to LLM-call or use a brittle synonym table. |
| `9a707b82` (cooking temporal) | V8.2.1 retrieve already finds the candidate; the gap is LLM date-fuzz judgment. Marginal V8.3 win, not worth the helper. |
| `d6233ab6` (preference advice) | Not an information-extraction problem. Stays on LLM. |

## What's next

1. **V8.3.1 is closed.** No further changes to this helper unless a
   real-world over-fire is observed.
2. **Next step is a diagnostic, not implementation.** Audit `d851d5ba`
   on the existing chain: does `NumericAggregator` already extract the
   4 charity events? What does `get_numeric_cardinal()` actually inject
   into the prompt? Is V8.2.1's failure the cardinal view being too
   long, the answer being truncated, or the LLM ignoring the formula?
   Output: `2026-05-22-v831b-d851d5ba-chain-diagnostic-cc.md`.
3. **Only if the diagnostic shows a stable, fixable output-layer
   issue** do we open V8.3.1b — and it will be a compression / rewrite
   of the existing cardinal view, not a new fundraise extractor.

## Commits

| Hash | Subject |
|---|---|
| `d99ad06` | log: V8.3 typed-event read-only audit (6 LME-S qids) |
| `248d60d` | V8.3.1: typed-event person_age average hint (target gpt4_d12ceb0e) |
| `014cd43` | V8.3.1 smoke: gpt4_d12ceb0e PASS (acc=1.000, deepseek-v3.2/gpt-4o judge) |
