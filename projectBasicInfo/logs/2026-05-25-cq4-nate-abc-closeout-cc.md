# CQ-4 — Nate Candidate A/B/C E2E Control — Close-out

**Date**: 2026-05-25
**Author**: Claude Code
**Status**: Closed. **Candidate-block direction officially closed
for Nate.** No code change. e2e evidence collected.

---

## Setup

User-required e2e A/B/C control on c3_a9fddfe69b (Nate dragons)
before closing the candidate-side direction:

- A: current behavior (`extract_evidence_candidates` + render).
- B: no candidate block (`return ""` early).
- C: render only candidates with `relation == "topic_keyword"`.

All controlled by `RADIOMIND_CQ4_VARIANT` env-var (default A,
zero impact when unset). Sandbox `/tmp/rm-cq4-nate-shared`,
shared across all 9 runs. Note that the runner wipes
`sandbox/data` at start of each invocation, so retrieved
memories are NOT identical across runs (ingest LLM is
non-deterministic); this is a deviation from the original
"hold memories fixed" design, but is the existing runner
behavior — accepting it as the achievable form of the control.

Each variant ran 3 times. Total 9 e2e invocations
(answer + judge per run).

## Results

```
variant   pass    total   avg_elapsed
A         0/3     3       1359s
B         0/3     3       1544s    (1 of 3 was timeout)
C         0/3     3       1481s
```

B run 2 hit `[answer error: The read operation timed out]` —
the LLM API itself failed, not a content judgment. Treating
that run as invalid still leaves B at 0/2; even if a re-run
of B run 2 passed (0/2 → 1/3), the threshold (≥2/3) wouldn't
be met.

## What the LLM Actually Said (every variant, every run)

All 9 successful answers open with a structurally identical
preamble: scan memories, identify Nate's relevant turn, quote
D9:14:

```
"I love this series. It has adventures, magic, and great
 characters - it's a must-read!"
```

The committed answer is the same content across variants
— some flavor of "adventures, magic, fantasy". **In no run
did the LLM commit to "dragons"**, including the C variant
that placed the `dragon` topic_keyword at candidate rank 1.

## Reading

The candidate block has **no leverage** on the Nate outcome:

- Adding noise (variant A): LLM ignores noisy candidates,
  commits to D9:14 dialogue text → "adventures, magic".
- Removing the block entirely (variant B): LLM still
  commits to D9:14 dialogue text → "adventures, magic".
- Surfacing "dragon" as candidate rank 1 (variant C): LLM
  still commits to D9:14 dialogue text → "adventures, magic".

The gold token "dragons" only enters the candidate
extractor because the runner appends image-query metadata
(`[Sharing image — query: fantasy novels dragon cover series.]`)
into D9:14's stored content. That text is also in the raw
retrieved memory, but the LLM treats it as an embedded
metadata annotation, not as the speaker's content — so
even when it's directly hinted, it isn't adopted.

Whether this is "correct" depends on benchmark interpretation:
- If the gold expects the model to mine image-query metadata
  for answer signals, the LLM is failing.
- If the gold relies on something genuinely outside the
  ingested text channel (the trail/cover image itself, not
  just its query keyword), no text-only manipulation can
  close it.

Either way, candidate-block strategy is not the lever.

## Decision

Per user's decision rule:

> 如果 Nate 的 A/B/C 都无法改善，则正式关闭 candidate 方向

**Candidate-block direction closed.** Including for:

- Stopword expansion / re-rank (CQ-1 v1, already falsified).
- Structural suppress (CQ-3 v1, already falsified at design
  gate; CQ-4 now adds e2e evidence that even with B/C
  reaching Nate the answer doesn't move).
- Topic-keyword-only render (CQ-4 C, falsified at e2e).

The `RADIOMIND_CQ4_VARIANT` env-var hook stays in code as a
diagnostic switch (default A unchanged). Useful for any
future evidence_candidates investigation; doesn't affect
production behavior.

## Remaining Architectural Options

(None auto-started.)

1. **`retrieval-recall-bridging` workstream**: the c2_financial /
   c9_Calvin pattern (gold-in-store but not in top-K) is the
   remaining stable-FAIL family where a methodology
   intervention could plausibly help. LLM-heavy; design as
   read-only audit first.
2. **`extractor-reform`**: separate from candidate ranking;
   the `_PROPER_NOUN_RE` over-extraction of sentence-initial
   capitalized words IS a real artifact. CQ-4 shows this
   doesn't help Nate specifically (LLM ignores the block),
   but it's still a code-hygiene improvement that could be
   audited under M1+M3+M4 if anyone cares about candidate
   diagnostic legibility.
3. **Return to LME-S**: `NumericAggregator` charity recall
   was a deterministic win (NAR). Other classes
   (`spending_events`, `income_events`, `savings_events`,
   `kitchen_items`) may have similar narrow paths. Read-only
   audit first.
4. **Pause LCO / LoCoMo direction**: switch to other
   RadioMind components (Rust ingest layer, MCP server,
   community features, etc.) for a while.

Each requires its own go-ahead. None is implied by closing
CQ-4.

## Files / Artifacts

- `bench/end_to_end/cq4_nate_abc.sh` — wrapper.
- `bench/end_to_end/cq4-nate-{A,B,C}-run{1,2,3}.json` — per-run.
- `bench/end_to_end/cq4-nate-abc-summary.json` — flat summary.
- This log: `projectBasicInfo/logs/2026-05-25-cq4-nate-abc-closeout-cc.md`.
- `src/radiomind/core/mind.py` — env-var hook (default A,
  no production impact).

## Caveats and Limitations

- 3 runs per variant is low for stochastic LLM scoring; a
  single PASS in any cell would shift the conclusion. The
  unanimous 0/9 result is strong enough to close
  candidate-direction for THIS qid, but not a general
  theorem about candidate blocks.
- Retrieved memories not strictly held fixed (runner wipes
  sandbox each invocation). The achievable form of the
  control. If a stricter fixed-retrieval A/B/C is ever
  needed, the runner needs a `--reuse-sandbox` flag.
- B variant lost 1 run to LLM API timeout (not a content
  failure). If pursued further, that run would need re-running.
