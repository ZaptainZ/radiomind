# LME-S Post-0.93 Failure-Family Audit (Batch 1)

**Date**: 2026-05-28
**Author**: Claude Code
**Status**: Read-only. No implementation. Per Codex's
recommendation, identifies whether any of the 4 prioritized
fails admits a narrow deterministic skill candidate.

---

## Scope

Per the user/Codex prioritization after the 0.93 baseline
closeout:

1. `bb7c3b45` — commit-side calibration / evidence-present
   abstain. **Highest priority** — not entity-norm, not
   subjective preference.
2. `b46e15ed` — event-cluster interval shape.
3. `gpt4_194be4b3` — instruments count (entity norm).
4. `gpt4_ab202e7f` — kitchen items count (entity norm).

Goal: per qid, judge whether a narrow deterministic skill
could close the gap without resorting to open-vocabulary or
subjective inference. NOT to implement.

Method:
- Stage 0: free regex over all user turns of the haystack —
  count key-entity hits.
- Stage 1: read the full content of gold-marked
  `answer_session_ids` to confirm the evidence chain.

## bb7c3b45 — "How much did I save on the Jimmy Choo heels?"

Gold: `$300`.

Evidence chain (both gold-marked sessions):

- Session `answer_de64539a_1` (2023/05/23, t0, USER):
  > "I was thinking of wearing my new Jimmy Choo heels that
  > I got at the outlet mall **for $200**..."
- Session `answer_de64539a_2` (2023/05/29, t0, USER):
  > "...some designer brands can be really pricey, like
  > Jimmy Choo heels, which I know **originally retailed for $500**."

Arithmetic: `$500 - $200 = $300` ✓ matches gold.

**This is a narrow deterministic skill candidate**, structurally
parallel to V8.2.3a `cashback_arithmetic_hint`:

| layer | savings-arithmetic | cashback-arithmetic (precedent) |
|---|---|---|
| Trigger | `how much did I save on [item]?` | `how much cashback at [merchant]?` |
| Anchor A | `got [item] for $X` (paid price) | `merchant has X% cashback` |
| Anchor B | `originally retailed/cost/listed for $Y` (original price) | `spent $Y at merchant` |
| Operator | `Y - X` (saving) | `X% * Y` (cashback) |
| Result | dollar saving | dollar cashback |

Risk surface: brand+item phrase must match on both anchors;
false positives possible if user mentions 2 prices of
different items. Trigger trigger surface needs auditing
across LME-S to bound blast radius (TBD pre-implementation).

V8.2.2a passed this qid (LLM committed "$300" directly);
the 2026-05-26 run abstained. Status: stochastic LLM
abstain — exactly the pattern a deterministic hint would
close (parallel to how cashback_arithmetic_hint closes
9aaed6a3).

**Recommendation**: open a separate pre-implementation
audit (`SavingsHint-1a`) to:

1. Regex-pre-screen LME-S 500 for the trigger
   `how much (did|do) I save on \[item\]`.
2. For each match, check whether the haystack carries the
   2-anchor structure (paid price + original price for same
   item). If only bb7c3b45 has the structure, ship narrow.
   If multiple do, design family.
3. Audit whether the trigger over-fires on questions where
   the user mentioned 2 unrelated prices nearby (false-
   positive risk).

Implementation deferred behind this pre-audit.

## b46e15ed — "How many months have passed since I participated in two charity events in a row, on consecutive days?"

Gold: `2`. Question date: `2023-04-18`.

Evidence chain (4 gold sessions, each carrying ONE charity
event):

| session | date | event |
|---|---|---|
| `answer_4bfcc250_4` | 2023-01-30 | Cancer Research Foundation gala |
| `answer_4bfcc250_3` | 2023-02-14 | 24-Hour Bike Ride |
| `answer_4bfcc250_2` | 2023-02-15 | Books for Kids book drive |
| `answer_4bfcc250_1` | 2023-03-19 | Walk for Hunger |

The "two consecutive days" pair is **2023-02-14 +
2023-02-15** (Tuesday + Wednesday). Reference_date minus
last_event_date: `2023-04-18 - 2023-02-15 = 62 days ≈
2 months`. Matches gold.

The user's text DOES NOT use the words "consecutive",
"in a row", or "back-to-back" (0 hits in stage-0 scan).
Only the question frames it as "two in a row". A
deterministic operator would need to:

1. Extract all events of class "charity" with a date.
2. Identify pairs separated by exactly 1 day.
3. Take the LAST event of that pair as the cluster's
   tail date.
4. Compute `(reference_date - tail_date) / ~30` months.

Step 1 (entity-class extraction) and step 2 (pair-finding
heuristic) make this NOT a narrow regex match — it requires
event-class tagging across multiple sessions.

This matches LSA-3's `event_cluster_interval_shape_gap`
classification. **Single-qid evidence**; LSA-3's deferral
recommendation stands ("only justify if cohort recurs").

**Recommendation**: hold defer. Cohort audit could be
sequenced later but is unlikely to find more cases — the
"two-on-consecutive-days, months since" shape is rare.

## gpt4_194be4b3 — "How many musical instruments do I currently own?"

Gold: `4` (Fender Strat / Yamaha FG800 / Pearl Export drum
set / Korg B1 piano).

Evidence chain across 5 gold sessions:

- Fender Stratocaster electric guitar — "5 years"
- Yamaha FG800 acoustic guitar — "8 years"
- Pearl Export 5-piece drum set — "haven't played in years"
  (still owned — user wants to SELL it, implying current
  ownership)
- Korg B1 piano — "about 3 years"

Distractors:

- Niece's violin (third-party, not user-owned)
- Ukulele (Cordoba / Kala / Fender CP-60S) — user is
  CONSIDERING buying, not yet owned

Deterministic counting needs:

1. First-person ownership phrases ("I've had", "my old",
   "my X") AND filter out third-party ("my niece's").
2. Future-tense / hypothetical filter ("thinking of",
   "considering").
3. Open-vocabulary brand-model normalization (Fender
   Stratocaster = my electric guitar).

These three filters are exactly the open-vocabulary entity
normalization Codex flagged as high-risk. Per LSA-2 label
this is `computation_high_risk` — defer.

**Recommendation**: hold defer. Not a narrow deterministic
candidate.

## gpt4_ab202e7f — "How many kitchen items did I replace or fix?"

Gold: `5` (kitchen faucet / kitchen mat / toaster / coffee
maker / kitchen shelves).

Evidence chain across 5 gold sessions:

- Kitchen shelves — "I finally fixed the kitchen shelves
  last weekend" ✓
- Kitchen mat — "replaced the worn-out kitchen mat in
  front of the sink with a new one from IKEA" ✓
- Kitchen faucet — "just replaced my old kitchen faucet
  with a new Moen one" ✓
- Toaster → toaster oven — "got rid of the old toaster
  and replaced it with a toaster oven" ✓
- Coffee maker — (likely in a session not fully visible
  here; user-haystack scan should confirm if a "replaced
  coffee maker" mention exists)

Distractors:

- Espresso machine (gift from sister, NOT replaced — new
  acquisition)
- Toaster oven itself (the REPLACEMENT, not a separate
  item)
- Sink (only mentioned as location, not replaced)

Deterministic counting needs:

1. Verb-context filter: `replaced/fixed/got rid of and
   replaced` (positive), exclude `donated/got as gift/just
   bought new`.
2. Kitchen-item closed inventory OR open-vocabulary
   "kitchen-X" matcher.
3. Dedup: the toaster→toaster oven replacement counts as
   ONE replacement of the old toaster, NOT two items.

Same shape as gpt4_194be4b3 — open-vocabulary entity norm
with verb-context filtering. Per LSA-2 label this is
`computation_high_risk` — defer.

**Recommendation**: hold defer. Not a narrow deterministic
candidate.

## Aggregate Decision

| qid | classification | next step |
|---|---|---|
| **bb7c3b45** | **narrow deterministic candidate** (savings arithmetic) | open `SavingsHint-1a` pre-implementation audit |
| b46e15ed | event_cluster_interval_shape_gap (single-qid; LSA-3 defer) | hold defer; cohort audit could refresh later |
| gpt4_194be4b3 | computation_high_risk (open-vocab entity norm) | hold defer |
| gpt4_ab202e7f | computation_high_risk (open-vocab entity norm + verb context) | hold defer |

**Bottom-line**: 1 of 4 audited qids has a clean narrow
deterministic shape. Three remain in defer. The recommended
sequence is:

1. `SavingsHint-1a` pre-implementation audit (regex-screen
   LME-S for "save on item" triggers + bound blast radius).
2. If audit passes, ship a small `savings_arithmetic_hint`
   helper mirroring `cashback_arithmetic_hint` architecture.
3. Defer b46e15ed / instruments / kitchen until either
   cohort evidence appears or a separate architectural
   workstream targets entity normalization.

No implementation in this audit. No code change.

## Files

- This log: `projectBasicInfo/logs/2026-05-28-post-093-failure-family-audit-cc.md`
- Related: `projectBasicInfo/logs/2026-05-25-lsa3-existing-path-audit-cc.md`
  (event_cluster_interval_shape_gap definition)
- Related: `projectBasicInfo/logs/2026-05-28-lme-s-n100-jab-protected-baseline-cc.md`
  (n=100 baseline + the 7 fails recorded there)
