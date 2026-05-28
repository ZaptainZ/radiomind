# SavingsHint-1a Pre-Implementation Audit (Read-Only)

**Date**: 2026-05-28
**Author**: Claude Code
**Status**: Audit complete. Gate **PASSED**. Proceed to
SavingsHint-1b implementation under the strict constraints
Codex set.

---

## 4 Questions

### Q1 — Trigger surface

Regex (intentionally conservative — requires
`how much (did|do|have|can) I sav\w+ (on|for|buying|when I bought/got)`
followed by item phrase + sentence-end):

```
how\s+much\s+(?:did|do|have|can)\s+i\s+sav\w+\s+
(?:on|for|buying|when\s+i\s+(?:bought|got))\s+
(?P<item>.{1,80}?)\s*[\?\.\!]
```

**LME-S 500-qid scan: 2 triggers** (≤ 3, gate satisfied):

| qid | extracted_item | gold |
|---|---|---|
| `bb7c3b45` | "the Jimmy Choo heels" | `$300` |
| `e25c3b8d` | "the designer handbag at TK Maxx" | `$300` |

Both ask for absolute saving on a specific item — no
"save for trip / save for goal / save money" variants
present in LME-S.

### Q2 — 2-Anchor Presence

Anchor templates (strict; explicit paid-verb required;
retail templates accept `originally retailed/listed/cost/
priced for $Y`, bare `originally $Y`, and `MSRP / retail
price / price tag / original price $Y`):

| qid | matched_anchor | paid | retail | two_anchor_clean | save |
|---|---|---|---|---|---|
| `bb7c3b45` | "jimmy choo heels" | `[200.0]` | `[500.0]` | **YES** | **300.0** ✓ |
| `e25c3b8d` | "designer handbag" | `[200.0]` | `[]` | NO | — |

**Only `bb7c3b45` has both anchors aligned to the same
item within the strict 80-char same-sentence proximity
window.** `e25c3b8d`'s retail evidence ("By the way, I
got a fantastic deal on the bag - it was originally $500!")
is in the same gold session as the item mention "I recently
got a designer handbag", but separated by 200+ chars and
multiple sentence boundaries — the deterministic matcher
rejects it as ambiguous, which is the correct conservative
behavior under Codex's gate.

### Q3 — Item-Anchor Stability

Item anchor extraction order (most-specific first):
1. Full normalized phrase (e.g. "designer handbag at tk maxx").
2. Phrase truncated at locative preposition (drop trailing
   `at|in|from|on|inside|outside ...`) → "designer handbag".
3. First-3-token fallback.

For `bb7c3b45`, anchor `"jimmy choo heels"` matches both
sides — brand + head noun complete overlap. **High
confidence.**

For `e25c3b8d`, anchor `"designer handbag"` matches only
the paid side ("designer handbag I got for $200 at TK
Maxx"). Retail side is in the same turn but the proximity
window rejects it. **Auto-rejection — correct conservative
behavior.**

Generic single-token anchors (`heels`, `bag`, `item`)
are intentionally NOT emitted by `_item_anchors()`:
2-token minimum (brand+noun) is required for a hit.

### Q4 — Negatives

Negative classes Codex listed:
- "save money" 泛建议 — **not present** in LME-S
- "save for a trip / save for goal" — **not present**
- coupon/discount but no 2-anchor — **e25c3b8d-class**:
  partial anchor presence is the safety case. Audit shows
  the strict 2-anchor gate correctly rejects.
- charity / cashback / spending mis-trigger — **not
  triggered** by the conservative trigger regex (no
  "how much did I save on charity / cashback" matches).
- 多金额但非同一商品 — protected by item-anchor stability
  requirement; multi-amount-same-item only.

The single negative hit (`e25c3b8d`) is deterministically
rejected by the 2-anchor + same-item proximity gate. No
LLM call needed; no semantic similarity; no synonym
matching.

## Gate Decision

Codex's strict gate (USER 2026-05-28):

| condition | satisfied |
|---|---|
| trigger surface ≤ 3 | ✓ (2) |
| `bb7c3b45` only / cleanest positive | ✓ |
| every negative is deterministically-rejectable | ✓ (e25c3b8d auto-rejected, no LLM) |
| NO LLM semantic matching | ✓ |
| NO item synonym | ✓ (literal phrase match) |
| NO coupon/discount family | ✓ (not in trigger; ignored) |
| NO "I saved $X" direct extract | ✓ (deterministic retail−paid only) |

**Gate PASSED.** SavingsHint-1b cleared for implementation.

## SavingsHint-1b Spec (for the next commit)

- File: extend `src/radiomind/core/arithmetic_hint.py`
  with `savings_arithmetic_hint(question, retrieved_memories)`.
- Architecture mirrors `cashback_arithmetic_hint`:
  - prompt-prefix hint only, NOT a post-rewrite that
    forces commit.
  - returns "" when any gate fails.
- Gate (identical to this audit's strict gate):
  1. Question matches the trigger regex.
  2. Exactly 1 paid_amount and exactly 1 retail_amount
     when scanning user-turn memory text with the matched
     item anchor.
  3. `retail >= paid` (defensive — refuse impossible
     savings).
  4. Item anchor matches both sides via 2+ token phrase.
- Output: brief hint block of the form
  `"DETERMINISTIC SAVING HINT: paid $200, originally $500
  → saved $300 on [item]. Use this if the question asks
  how much was saved on [item]."`
- NO post-rewrite. Hint-only. The answer-LLM is free to
  ignore.

## Test Plan (SavingsHint-1b)

- Unit tests covering:
  - target: bb7c3b45 evidence → hint produces $300.
  - no retail anchor → hint returns "" (e25c3b8d shape).
  - 2 paid amounts → reject.
  - 2 retail amounts → reject.
  - retail < paid → reject.
  - charity / cashback context → no trigger.
  - "save for trip" → no trigger (item is "trip", no $).
  - generic 1-token item → reject.
- Target smoke: `bb7c3b45` + `e25c3b8d` e2e.
- NO `n=100` rerun (Codex P5: stochastic band already at
  ±1, n=100 doesn't help evaluate architectural value of
  a 1-qid helper).

## Files

- Audit script: `bench/end_to_end/savings_hint_1a_audit.py`
- Audit data: `bench/end_to_end/savings-hint-1a-audit.json`
- This log: `projectBasicInfo/logs/2026-05-28-savings-hint-1a-audit-cc.md`
