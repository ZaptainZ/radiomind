# NAR-3 — Deterministic Charity-Context Recognizer (Design)

**Date**: 2026-05-22
**Author**: Claude Code
**Status**: Design only. No code yet. NAR-4 writes tests, NAR-5 implements.
**Inputs**: NAR-1 5-run isolated re-ingest matrix; NAR-2 root-cause findings.

---

## Why a Recognizer Is the Right Intervention

NAR-1 + NAR-2 confirmed three layers of LLM stochasticity all
contribute to `d851d5ba`'s 0/5 PASS rate on the existing chain:

1. **Extraction**: LLM batch extractor misses E2/E3 entirely in 2/5
   runs; E1 (`"helped raise over $1,000 ... at a charity bake sale"`)
   never receives `entity_class=charity_donations` in any run.
2. **Classification fallback**: when LLM returns no `entity_class`,
   the regex `cls_hint` resolves via `_amount_verb_to_class`. That
   table maps only `"raised"` (past tense) to `charity_donations` —
   the bake-sale phrase says `"helped raise"` (base form), so the
   hint resolves to `amount_events`, not `charity_donations`.
3. **Trinity refinement**: same evidence block produces revoke
   decisions ranging from -0 to -7 events across runs. Sometimes
   wipes the entire class.

The cleanest fix lives where the variance enters: **at amount
extraction time, give events a deterministic class hint built from
receiver context, not just verb tense.** A deterministic recognizer
that decides "charity vs not" with regex over the full sentence
sidesteps both the LLM-extractor variance and the trinity revoke
problem, because:

- A regex with high-precision charity-context signals can be tested
  in isolation; the test set itself becomes the spec.
- The recognizer is one-way: it can *promote* an event to
  `charity_donations`, never demote it. So it cannot delete events
  the LLM was right about; it can only add the events the LLM
  missed.
- A `recognizer_class=charity_donations` carries higher priority
  than `_amount_verb_to_class`'s ambiguous fallback. We do NOT touch
  events the LLM classified into another specific bucket
  (`spending_events`, `income_events`, etc.) — only the
  `amount_events` / null-class events get reclassified.

What we are NOT doing:

- Not patching the cardinal view (output-side fix; already
  V8.3.1b's verdict that output-side won't help).
- Not changing the LLM batch prompt — too unstable to chase with
  prompt tweaks.
- Not introducing a new entity_class — we lean on the existing
  `charity_donations` row.

---

## Failure Mode Spec (from NAR-1 evidence)

Each gold event in `d851d5ba`:

| ID | Amount | Source phrase fragments | Why it currently lands wrong |
|---|---|---|---|
| E1 | $1,000 | "I helped raise over $1,000 for the local children's hospital at a charity bake sale" | Verb is `raise` (base form), not `raised`. `_amount_verb_to_class("raise")` returns `amount_events`. |
| E2 | $250 | "I just ran 5 kilometers in the 'Run for Hunger' charity event ... raising $250 for a local food bank" | Verb pattern says `raising`; second AMOUNT_PATTERN regex (conjunction-led) catches it. But LLM batch sometimes drops the turn entirely → 0/2 events extracted in 2/5 runs. |
| E3 | $500 | "I recently completed a charity fitness challenge in February and managed to raise $500 for the American Cancer Society" | Same `raise` base-form trap as E1. Also dropped from LLM batch in 2/5 runs. |
| E4 | $2,000 | "I helped raise over $2,000 for the local animal shelter on January 20th" | Same `helped raise` trap as E1. Always extracted from t0 due to "charity cycling event" context phrase nearby. t6 duplicate triggers dedup failure (separate problem, not this NAR's scope). |

False-positive observed (5/5 runs): `$5,000 music benefit concert
... raised over $5,000 for the local music education program`. LLM
batch tags this as `charity_donations`. The recognizer must NOT
strengthen this — leave LLM's call alone OR explicitly classify it
out.

Cardinal view has a separate scope-filter using literal `\bcharity`
on the phrase. NAR's recognizer adds to extraction; it doesn't
change the scope filter.

---

## Recognizer Spec

### Trigger (one of these conditions, regex-AND inside each)

**T1. Receiver names a charity-context entity**

```
\bfor\s+(?:the\s+|a\s+|an\s+|our\s+|my\s+)?(?:local\s+)?
   (charity|charities|fundraiser|fund|nonprofit|non[\- ]profit
   |\w+\s+foundation|\w+\s+society|\w+\s+hospital
   |food\s+bank|animal\s+shelter|homeless\s+shelter
   |american\s+cancer\s+society|red\s+cross
   |doctors\s+without\s+borders|salvation\s+army
   |hospice|charity\s+bake\s+sale)\b
```

Examples that fire:
- `"raise $1,000 for the local children's hospital"` ✓ (hospital)
- `"raised $250 for a local food bank"` ✓
- `"raise $500 for the American Cancer Society"` ✓
- `"raise $2,000 for the local animal shelter"` ✓

Examples that do NOT fire:
- `"raised $5,000 for the local music education program"` ✗ (education, not charity org)
- `"spent $50 for groceries"` ✗
- `"$3.99 for bread"` ✗

**T2. Sentence contains literal `charity` + raise/donate verb**

```
\b(?:donat|rais|contribut|gave\s+to|donate\s+to)\w*
   .{0,40}?\$\s*\d[\d,]*.{0,60}?\bcharit
```

Catches the case where receiver wording is vague but `charity` is
adjective on the event itself:
- `"I helped raise over $1,000 ... at a charity bake sale"` ✓
- `"managed to raise $500 ... charity fitness challenge"` ✓

**T3. Money-event verb + known charity org (case-insensitive)**

Closed list of charity-org keyword stems:
```
red cross | american cancer society | doctors without borders
| salvation army | unicef | habitat for humanity | st. jude
```

Examples:
- `"donated $200 to UNICEF"` ✓
- `"raised $500 for the American Cancer Society"` ✓ (also catches via T1)

### Output

When ANY trigger fires for a sentence containing `$N`:

- Emit a candidate `{polarity: "amount", amount: N, cls_hint: "charity_donations", phrase: <full sentence>, turn_id: ..., recognizer: "deterministic-charity"}`.
- This candidate is added alongside whatever LLM / existing regex
  produced. Dedup remains class-aware
  (`(turn_id, polarity, amount, class)`), so we don't double-count.

When NO trigger fires: emit nothing. Recognizer is silent — does not
demote events.

### Priority in `_classify_batch`

Current code (`numeric_aggregator.py:1192`):

```python
if not c.get("entity_class"):
    c["entity_class"] = c.get("cls_hint") or "amount_events"
```

Change required (in NAR-5):

```python
if not c.get("entity_class"):
    c["entity_class"] = c.get("cls_hint") or "amount_events"
# NEW: deterministic charity recognizer overrides amount_events
# fallback when it was a hard match
if (
    c.get("recognizer") == "deterministic-charity"
    and c.get("entity_class") in ("amount_events", "", None)
):
    c["entity_class"] = "charity_donations"
```

This is a one-way upgrade: never moves an event OUT of a non-generic
class. The recognizer only rescues events that would otherwise have
no specific class.

### Trinity refinement interaction

`_refine_amount_events` runs trinity on the assembled events and may
revoke any of them. To stop trinity from wiping deterministic-
recognizer events:

- Tag the history record's `reason` field as `amount_charity_det`
  (instead of plain `amount`) when the deterministic recognizer
  contributed.
- In `_refine_amount_events`, exclude `amount_charity_det` rows from
  the candidate revoke list. Deterministic events are protected.

This is a small surgical change; it preserves trinity's role for
LLM-classified events (which can be wrong) while protecting the
events whose classification is regex-deterministic and thus
verifiable from the sentence text alone.

---

## Negative Coverage (what the recognizer must NOT match)

These all appear in real LME-S haystacks and would be false
positives without explicit exclusion:

| Sentence | Why not charity |
|---|---|
| `"I spent $50 on groceries"` | `spent` verb, not `raise/donate`; receiver isn't charity-context. |
| `"I bought concert tickets for $200"` | `bought`, not raise/donate. |
| `"I gave my niece $50 for her birthday"` | "for her birthday" — family transfer, not charity. |
| `"My rent went up to $1,500"` | No raise/donate verb. |
| `"I earned $300 freelancing"` | `earned`, income. |
| `"I got $50 cashback at SaveMart"` | cashback, not donation. |
| `"saved $20 with the coupon"` | savings. |
| `"$5,000 raised for music education"` | T1 doesn't fire (education ≠ charity org); T2 doesn't fire (no `charity` literal); T3 doesn't fire (no named charity). Recognizer stays silent → LLM's classification stands. |

Specifically the last one is the music-benefit false positive
we observed in NAR-1. NAR-3 leaves the LLM's `charity_donations`
classification untouched (recognizer can't demote), but doesn't
strengthen it either. The boundary is left where the LLM put it.

### Family-transfer guard

If T1 receiver pattern is followed by a family-relation noun
(`niece|nephew|sister|brother|cousin|mom|dad|aunt|uncle|kid|son|daughter|wife|husband|partner`),
don't fire even if the surface looks like charity. Example:
`"gave $500 to my brother for his charity event"` — boundary case;
gold here would prefer NOT charity because giver-receiver is family.

---

## What this design does NOT promise

- **Doesn't fix LLM extraction misses** (E2/E3 dropped entirely in
  2/5 runs). Recognizer runs over user turns the regex amount path
  already iterates — same content surface. If the regex amount
  pattern doesn't match in a run (which IS deterministic), the
  recognizer can't see the turn either. Recall improvement requires
  also tightening AMOUNT_PATTERNS (out of NAR-3 scope).
- **Doesn't fix dedup of same-event t0/t6.** That is a separate
  cardinal-side fix (NAR-deferred).
- **Doesn't fix cardinal view's inflated total in prompt header.**
  Also separate (out of scope here; record in NAR-9 future work).

What NAR-3 does promise: when an amount in raw turn text has a
charity-context receiver or charity literal, the deterministic
recognizer guarantees it lands in `charity_donations` regardless
of LLM batch output or trinity vote.

---

## Test Plan Outline (NAR-4 will codify)

| Case | Sentence | Expected output |
|---|---|---|
| pos-1 (E1) | "I helped raise over $1,000 for the local children's hospital at a charity bake sale" | amount=$1,000, cls_hint=charity_donations |
| pos-2 (E2) | "I just ran 5 kilometers in the 'Run for Hunger' charity event and raising $250 for a local food bank" | $250, charity_donations |
| pos-3 (E3) | "managed to raise $500 for the American Cancer Society" | $500, charity_donations |
| pos-4 (E4) | "I helped raise over $2,000 for the local animal shelter on January 20th" | $2,000, charity_donations |
| neg-1 | "I spent $50 on groceries" | not emitted (or amount_events) |
| neg-2 | "I bought concert tickets for $200" | not emitted |
| neg-3 | "I gave my niece $50 for her birthday" | not emitted (family-guard) |
| neg-4 | "I got $50 cashback at SaveMart" | not emitted |
| neg-5 | "$5,000 raised for music education" | recognizer SILENT (no T1/T2/T3 match) |
| neg-6 | "rent went up to $1,500" | not emitted |
| boundary-1 | "I donated $200 to UNICEF" | charity_donations (T3) |
| boundary-2 | "gave $500 to my brother for his charity event" | not emitted (family guard wins over T2) |

---

## Implementation Files (for NAR-5)

- `src/radiomind/refinement/numeric_aggregator.py`:
  - Add module-level constant `CHARITY_RECEIVER_KEYWORDS`,
    `CHARITY_ORG_KEYWORDS`, `FAMILY_RELATION_KEYWORDS`.
  - Add private fn `_deterministic_charity_match(content) -> bool`.
  - In `_extract_regex_candidates` (the `for pat in AMOUNT_PATTERNS`
    block around line 1158-1176), after building the candidate
    dict, call the deterministic match on the full turn `content`;
    when it fires, set `candidate["recognizer"] = "deterministic-charity"`
    and override `cls_hint` to `charity_donations`.
  - In `_classify_batch` (line 1192), add the one-way upgrade rule.
  - In `_apply_delta` (or wherever amount history reason is set),
    tag deterministic-recognizer events with `reason="amount_charity_det"`.
  - In `_refine_amount_events`, skip rows where
    `h.get("reason") == "amount_charity_det"`.
- `tests/test_numeric_aggregator_charity_recall.py`: NAR-4.

## Decision

Design ready. Next: NAR-4 writes failing tests against the contract
above. NAR-5 implements minimally to make tests pass without
breaking existing tests.
