# NAR-8 — Trigger-face audit of `detect_charity_amounts` (offline)

**Date**: 2026-05-22
**Method**: scan all 499 LME-S qids' user turns containing `$`,
run `detect_charity_amounts(content)`, bucket the firing qids by
question intent (charity / money-spend / other).
**No LLM calls. No e2e bench runs.**

## Aggregate

- Money-bearing user turns scanned: ~hundreds across 499 qids.
- Qids with ≥1 recognizer fire: **67 / 499**.

## Bucket A — Charity-themed questions (5 qids)

These are exactly the questions where firing is desired. The
recognizer should help, not hurt.

```
078150f1: How much more money did I raise than my initial goal in the
          charity cycling event?
129d1232: How much money did I raise in total through all the charity
          events I participated in?
a3838d2b: How many charity events did I participate in before the 'Run
          for the Cure' event?
d851d5ba: How much money did I raise for charity in total?       ← target
gpt4_b0863698: How many days ago did I participate in the 5K charity
               run?
```

NAR-5 effect on this bucket: increased recall into
`charity_donations`. d851d5ba is verified by NAR-6; the other four
likely see analogous benefit (not separately bench-verified — they
weren't FAILs that needed fixing, but better recall doesn't hurt
the cardinal view they wouldn't have queried into otherwise, since
`gpt4_b0863698` asks "how many days ago" which doesn't trigger
`get_numeric_cardinal()`).

## Bucket B — Money/spending questions, NOT charity (10 qids)

```
1c549ce4: What is the total cost of the car cover and detailing spray?
311778f1: How many hours did I spend watching documentaries?
37d43f65: How much RAM did I upgrade my laptop to?
4bc144e2: How much did I spend on car wash and parking ticket?
51a45a95: Where did I redeem a $5 coupon on coffee creamer?
9aaed6a3: How much cashback did I earn at SaveMart last Thursday?
aae3761f: How many hours in total did I spend driving?
af8d2e46: How many shirts did I pack for my 5-day trip to Costa Rica?
b5ef892d: How many days did I spend on camping trips?
bb7c3b45: How much did I save on the Jimmy Choo heels?
```

These all have charity user turns in their haystack (multiple
LME-S users are charity-active), so the recognizer correctly
classifies those turns into `charity_donations`. But the QUESTIONS
ask about a completely different cardinal class (cost / cashback /
spending / time-spent / count). `get_numeric_cardinal()` routes
via `extract_focus_entity(query)` which extracts the query's focus
noun — none of these queries contain "charity" / "donation" /
"raise". Therefore `query_by_focus` never lands on the
`charity_donations` entry, and the recognizer's extra rows in
that entry are dormant.

**Verdict**: dormant rows, zero answer-side pollution expected.

## Bucket C — Other questions, no money intent (52 qids)

```
0862e8bf: What is the name of my cat?
1c0ddc50: Can you suggest activities during my commute?
... (52 total)
```

These questions don't go through the cardinal/numeric path at
all. `get_numeric_cardinal()` early-returns when the query isn't
classified as `numeric_cardinal` by attention. Recognizer fires
in their haystack are storage-only side effects with no answer-
side surface.

**Verdict**: completely invisible to these queries.

## Combined verdict

- True positive (intended): 5 charity questions.
- False positive into answer: **0 estimated**, based on
  query-routing analysis. (Not bench-verified yet — would need
  to run all 67 qids' e2e to be 100% certain. Selecting a few
  high-risk candidates for spot-check in NAR-7 if budget allows.)
- True negative (untouched): 432 of 499 qids never fire the
  recognizer.

## What this audit does NOT prove

- A live n=100 bench could still find a regression we can't
  predict from offline analysis (e.g., LLM seeing a longer
  `charity_donations` history block somewhere it didn't before,
  and getting confused). Cost-benefit favors not running n=100;
  the d851d5ba e2e smoke (NAR-7) is the cheaper validation.
- The 10 Bucket-B qids' answer correctness is unchanged from
  pre-NAR-5 by this analysis, BUT we haven't measured it. A
  separate regression check would need to run those qids
  pre/post NAR-5.

## Decision

Trigger surface is acceptable. No pollution path found in
analysis. Continue to NAR-7 e2e smoke on d851d5ba to validate
answer-side; if PASS, recommend full merge in NAR-10.
