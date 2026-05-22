# V8.3.1b — `d851d5ba` Existing-Chain Diagnostic (Read-Only)

**Date**: 2026-05-22
**Author**: Claude Code
**Type**: Read-only diagnostic. **No code changes.**
**Conclusion preview**: **Do NOT open V8.3.1b as a new helper.** The
existing chain is architecturally correct; remaining variance is an
ingest-side reliability issue, orthogonal to the V8.3 typed-event /
output-hint family.

---

## Audit Scope

Codex's V8.3.1b plan: before implementing anything, audit the existing
`NumericAggregator` + `get_numeric_cardinal()` chain for `d851d5ba`
(charity sum, gold = $3,750). Answer five questions, then decide
whether to:

- (a) compress / rewrite the existing cardinal view,
- (b) concede and keep the LLM as-is, or
- (c) something else entirely (ingest-side fix).

## Method

Evidence sources used (no live re-ingest needed — older fix commits
already exposed the relevant state):

- `src/radiomind/core/mind.py:1783-2094` — `get_numeric_cardinal()`
  implementation: scope filter, dedup, evidence chain, inline
  arithmetic, `★ MUST be` directive.
- `src/radiomind/refinement/numeric_aggregator.py:110-280` —
  `charity_donations` class definition + LLM extraction prompt +
  regex supplement.
- Historical fix commits: `92b0159` (always-on regex supplement),
  `0c5d928` (evidence chain), `a48acb6` (scope-filter + dedup).
- V8.2.x bench artefacts:
  - `bench/end_to_end/lme-s-v82-1-n100.json` per_query[d851d5ba]
  - `bench/end_to_end/lme-s-v822a-n100.json` per_query[d851d5ba]
  - `bench/end_to_end/lme-s-v822a-n100.judge-fixed.json` per_query[d851d5ba]
- `/tmp/rm-e2e-lme-s-v822a/data/knowledge.db` — V8.2.2a sandbox
  (post-overwritten by later runs; cardinal entries from the
  original V8.2.2a d851d5ba domain are no longer present).

Important harness caveat for this audit: `run_longmemeval_mem0.py:764`
truncates the saved `answer` field to `[:400]` chars. None of the
saved bench JSONs include the LLM's final emitted number — only the
preamble. Conclusions about whether V8.2.1 abstained or computed a
wrong number rely on the judge's `verdict_tail`, which paraphrases
what it saw.

## The Five Questions

### Q1. Does `NumericAggregator` extract the 4 charity events?

**Answer: SOMETIMES — non-deterministic across runs.**

Evidence:

- `numeric_aggregator.py` runs a two-pass extraction at ingest:
  LLM-based class+amount extraction, then a regex supplement that
  fires unconditionally and dedupes against the LLM pass on
  `(turn_id, polarity, amount)`. The `charity_donations` class is
  explicitly defined with strict guards ("Generic gifts, purchases,
  rent, bills, family transfers are NOT charity").
- Commit `92b0159` (after the regex-supplement fix) reported: for
  `d851d5ba`, ingest captured **6 charity amount events** in one
  FM run, producing `DETERMINISTIC CHARITY TOTAL: $2,750`.
- Commit `0c5d928` explicitly states the unresolved variance:
  > "ingest-time LLM extraction is non-deterministic despite
  > temperature=0. Across runs on d851d5ba the cardinal captured
  > between **3 and 7 events**."

So the gold count is 4 (bake-sale $1,000, food-bank run $250, fitness
challenge $500, animal-shelter $2,000). The aggregator does NOT
deterministically capture exactly these four — it captures a
fluctuating set, and the four gold events are not always all present.
The known recurring miss is the **charity bake sale $1,000** event:
its source phrase ("volunteered at a charity bake sale and it was
amazing to see…") doesn't always survive class classification +
scope-filter as `charity_donations`.

### Q2. What does `get_numeric_cardinal()` inject for this question?

**Answer: a deterministic CHARITY TOTAL block with per-event evidence
chain and inline arithmetic — already very explicit.**

Predicted shape (derived by reading `mind.py:1909-2094`; not freshly
verified against a live re-ingest because the V8.2.2a sandbox's
`lme_49` cardinal entry was overwritten by later V8.2.3a smoke runs):

```
DRAFT CARDINAL VIEW (extracted at ingest-time — use as an anchor;
only override when retrieved memories clearly contradict it, not on
mere wording differences):
- charity_donations: total_amount=$N,NNN.NN (K events). Per-event evidence:
  · raised $1,000 :: I helped raise over $1,000 for the local children's hospital… [tid]
  · raised $250 :: ran 5 km in the "Run for Hunger"… [tid]
  · raised $500 :: charity fitness challenge in February… [tid]
  · raised $2,000 :: helped raise $2,000 for the local animal shelter… [tid]
  · raised $1,000 :: …  ← DEDUPED (same amount, same session)
  · raised $5,000 :: music benefit concert raised $5k for education…  ← FILTERED OUT (no 'charity')

  ⇒ DETERMINISTIC CHARITY TOTAL: $K,KKK
    Evidence chain (each item charity-scoped, deduplicated,
    sum computed by RadioMind, not LLM):
      [✓] $1,000  —  @ answer_5cdf9bd2_2_t0
              source: "...volunteered at a charity bake sale..."
      [✓]   $250  —  @ answer_5cdf9bd2_1_t0
              source: "..."
      [✓]   $500  —  @ answer_5cdf9bd2_3_t0
              source: "..."
      [✓] $2,000  —  @ answer_5cdf9bd2_4_t0
              source: "..."
      [✗ SCOPE] $5,000 — @ d77d4ac9_1_t6 — excluded because
              source has no 'charity': "..."
    Arithmetic: $1,000 + $250 + $500 + $2,000 = $3,750
    ★ Your final answer MUST be $3,750. The chain above is
      verifiable line-by-line — each event's source snippet is shown
      with its turn id. … Trust the chain.
```

When all 4 gold events are captured at ingest, this block correctly
arrives at `$3,750` and tells the LLM in absolute terms what to
answer. When a gold event is missing (e.g. bake sale → wrong class),
the block reports a partial total like `$2,750` — and the LLM is
asked, by the block's "use as an anchor; only override when retrieved
memories clearly contradict it" wording, to cross-check raw memories
and add back any missed events.

### Q3. Was V8.2.1's failure due to truncation, the DRAFT block, or the LLM ignoring the formula?

**Answer: LLM diverged from the cardinal floor. NOT truncation. NOT a
block-design defect.**

Evidence (from `verdict_tail`, since the saved `answer` is truncated):

- V8.2.1 `verdict_tail`:
  > "the total of $3,750. Therefore, the response is not semantically
  > equivalent to the correct answer." → judge concluded the LLM
  > emitted a number that was NOT $3,750.
- V8.2.2a `verdict_tail`:
  > "confirms the total amount raised for charity as $3,750.
  > Therefore, the model response is correct." → LLM emitted $3,750.

Same prompt structure in both runs (cardinal is prepended at
`run_longmemeval_mem0.py:635` after atomic/cashback/role_guard
sections; no V8.2.1→V8.2.2a change touched the cardinal pipeline).
The delta is pure LLM stochastic variance on the final commit step:
- Run A: cardinal said e.g. $2,750 floor; LLM cross-checked raw
  memories, found missing $1,000 bake sale, added it → $3,750 ✓
- Run B: same cardinal floor; LLM either trusted the floor blindly,
  or re-tallied raw memories and got a different total → wrong ✗

No evidence the DRAFT block is being IGNORED — the V8.2.1 answer
preamble explicitly says "I must also consider the DRAFT CARDINAL
VIEW provided at the start, which gives a determ[inistic…]". The
model saw it and acknowledged it. The divergence happens in the
final commit step, not in the reading.

### Q4. Is V8.2.2a's PASS stable?

**Answer: No. n=1 sample is not stability.**

Observed cross-version distribution:

| Run | Outcome |
|---|---|
| V8.2.1 (single n=100) | FAIL |
| V8.2.2a (single n=100) | PASS |
| V8.2.2a judge-fixed (post-hoc judge re-run) | PASS (same answer text) |

That's 1 PASS / 1 FAIL across distinct LLM-call sessions on the same
qid. Commit `0c5d928`'s own caveat (ingest captures 3-7 events across
runs) implies the upstream variance feeds directly into final-answer
variance. Expect this qid to PASS roughly when (a) ingest captured
all 4 gold events, OR (b) ingest captured ≥3 and the LLM cross-
checked correctly. Combined PASS rate is probably 40-70% on a single
run, not 100%.

### Q5. Recommendation: compress, concede, or other?

**Answer: CONCEDE for V8.3.1b. Do not open this as a new helper.**

Why "compress the existing cardinal view" is the wrong intervention:

- The cardinal block IS already compact relative to what it does
  (one header + per-event lines + arithmetic + ★MUST). Shortening
  it wouldn't change the failure mode, because the LLM IS reading
  it (see V8.2.1 preamble acknowledgement).
- The cardinal already includes the strongest commit directive the
  prompt has: `★ Your final answer MUST be $3,750. … Trust the
  chain.` This is the same shape as V8.2.3a's hint format. There is
  no stronger output-side directive to add.

Why a V8.3.1-style typed-event helper would be the wrong intervention:

- It would either (a) duplicate the cardinal view, or (b) hard-pin
  `$3,750` when the cardinal can only justify $2,750-$3,750 depending
  on ingest. Hard-pinning is a hack: it works only when we already
  know the gold, which is exactly what the helper isn't supposed to
  rely on.
- Codex flagged this concern when scoping V8.3.1: "V8.2.2 不该做
  confidence threshold" / "不应做 deterministic retrieval" / "不要继
  续 V8.2.x 这种单点 helper 了". A `d851d5ba`-targeted hint would
  recreate exactly that critique.

Where the real fix lives (out of V8.3 scope):

- The root cause is **ingest-time class-classification recall**:
  the charity bake-sale phrase ("volunteered at a charity bake sale
  and it was amazing to see how much…") doesn't consistently land in
  `charity_donations`. The current pipeline runs LLM + regex
  supplement; the LLM is non-deterministic, and the regex doesn't
  scope-tag bake-sale as charity by itself.
- A targeted ingest-side fix would be in `numeric_aggregator.py`:
  expand the `charity_donations` regex/heuristic to recognize
  "charity bake sale", "fundraiser", "for the food bank/animal
  shelter/American Cancer Society" as charity-context phrases. This
  is a NumericAggregator refinement, not a V8.3 typed-event helper.
- That work belongs to a separate `numeric-aggregator-recall`
  workstream if we want to lift `d851d5ba` from flaky to stable.
  V8.3 / V8.3.1 / V8.3.1b should NOT carry it.

## Decision

| Option | Verdict |
|---|---|
| Open V8.3.1b as a new helper | **No.** Existing chain already does the right thing on the output side. |
| Compress the cardinal view | **No.** Block is already compact; compression doesn't change failure mode. |
| Hard-pin `$3,750` via a typed-event hint | **No.** Requires gold-leakage; violates V8.3.1's narrow-helper philosophy. |
| Ingest-side recall fix in `NumericAggregator` | **Possible, but out of V8.3 scope.** Belongs to a `numeric-aggregator-recall` follow-up if d851d5ba stability is a priority. |
| Concede d851d5ba as flaky and move on | **Recommended for V8.3.1b.** |

V8.3 typed-event family (V8.3.1 person_age) stays scoped to *new*
deterministic computations that today's pipeline doesn't already
attempt. `d851d5ba` is not in that bucket — it has a deterministic
computation, and the missing piece is upstream recall.

## What this audit did NOT do

- No live re-ingest of `d851d5ba` to capture today's exact cardinal
  output. The V8.2.2a sandbox's `lme_49` cardinal entry was
  overwritten by subsequent V8.2.3a smoke runs. A future targeted
  reproduction would need ~5-10 min of ingest + ~$ of LLM budget;
  optional, the conclusions above are derived from code + historical
  fix-commit evidence.
- No code changes anywhere. The repository state on this branch is
  identical before and after this audit.
- No new tests, no new bench runs.

## Cross-references

- V8.3 audit (audit-only, 6 LME-S qids):
  `2026-05-21-v83-typed-event-audit-cc.md`
- V8.3.1 person_age close-out (the green-light direction):
  `2026-05-22-v831-person-age-typed-event-cc.md`
- Original cardinal-view design: commit `0c5d928`
- Always-on regex supplement: commit `92b0159`
- Scope-filter + dedup: commit `a48acb6`
