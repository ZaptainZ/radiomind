# RerankerAlternative-1b — query-adaptive RRF gate audit (held-out)

**Date:** 2026-06-15
**Author:** Claude Code (cc)
**Type:** READ-ONLY offline audit. No runtime change, no cloud, no full benchmark,
no new deps. Goal: decide whether method C (query-adaptive RRF, the 1a OPEN
candidate) can be safely gated BEFORE any runtime prototype.

## Questions

1. Which query types are safe for C? 2. Which must skip? 3. Can we reuse
BioLocal-1b's do-no-harm gate (`anchored == facet_rerank.should_rerank`)? 4. Is
C's win a general mechanism, or 19-qid small-sample luck?

## Method

`bench/end_to_end/reranker_gate_audit.py`. Two stages:
1. **Cross the 1a 19 qids by query-class.** Per-class C win/harm vs dense:
   `anchored` 2/0, `open` 3/3, `temporal_or_ordering` 3/1. → hypothesis: gate C to
   the `anchored` class only (which equals BioLocal-1b's `should_rerank`).
2. **Out-of-sample test of that gate** on **59 held-out qids** (first 59 dataset
   qids NOT in the 1a 19), computing dense baseline + C + C_gated (anchored-only).
   Baseline = local ONNX dense (required; BLOCKS if absent, never remote). Run
   under py3.12 + `[embedding]`.

## Result — the gate hypothesis is FALSIFIED out-of-sample

Held-out N=59, C win/harm vs dense baseline by class:

| class | n | ungated C win/harm | C_gated (anchored-only) win/harm |
|---|---|---|---|
| anchored | 11 | **1 / 2** | 1 / 2 |
| open | 40 | **16 / 3** | 0 / 0 |
| temporal_or_ordering | 8 | 1 / 3 | 0 / 0 |
| **TOTAL** | 59 | **18 / 8** | **1 / 2** |

- The 19-qid pattern **flipped**: `anchored` went from "safe 2/0" to **net-harm
  1/2** (harms: 25e5aa4f 11→16 "where did I complete my Bachelor's", 3d86fd0a 1→6
  "where did I meet Sophia"); `open` went from coin-flip 3/3 to **16/3 winner**.
- **The proposed anchored-only gate produces NET HARM on held-out (1 win / 2
  harms).** The 19-qid gate would have shipped a net-harmful change.
- **BioLocal-1b's gate does NOT transfer to C.** They operate in different
  regimes: BioLocal-1b rescues when FTS returns *nothing* (bare-install, no
  embedder); C re-fuses the *dense* pool (embedder present). The
  `anchored == safe` equivalence is regime-specific and broke here.

## What IS robust

- **C is net-positive OVERALL, and that generalizes:** held-out mean recall@5
  0.780 → 0.847 (+0.067); 18 wins / 8 harms (net +10). The 1a 19-qid run was also
  net-positive (8 wins / 4 harms). The *aggregate* lift replicates across samples.
- What does NOT replicate is **which queries** win/lose by class — so harms
  (~8/59 ≈ 14%) are NOT concentrated in a query-class we can gate on.

## Answers

1. **No query class is reliably safe for C.** `anchored` looked safe on 19, harmed
   on held-out. 2. **Class-based skipping doesn't work** — the harmful class is not
   stable. 3. **No, BioLocal-1b's gate is not reusable for C** (different regime;
   it failed out-of-sample). 4. **C's aggregate win is general; its per-class harm
   pattern is NOT — the 19-qid per-class signal was small-sample luck** (~5-8
   qids/class is too few; the pattern inverted at n≈11-40/class).

## Verdict — PARK the C runtime prototype (class-gate path falsified)

Per the standing rule ("only ship C to runtime once the gate is proven stable; do
not bare-wire C"), and since 1b **disproves** the class-based gate, C does NOT
advance to a runtime prototype now.

C is not dead — its overall net benefit is real and replicated. But a safe runtime
form needs a **non-class gate** (e.g. confidence/agreement-based: apply C only when
dense top-k is low-confidence, or when C and dense strongly disagree), validated on
its OWN fresh held-out. Crucially, do NOT now propose an "open-only" gate from THIS
held-out (open 16/3) and call it proven — that would repeat the exact overfitting
error this audit just caught; it would need an independent validation set first.

If pursued → **RerankerAlternative-1c:** design + held-out-validate a confidence-
based (not query-class) gate for C. Until then: PARK; **local cross-encoder
reranker remains the advanced best-quality option** (still no head-to-head vs C).

## Methodology lesson

Per-class win/harm rates on a curated ~19-qid set (≤8 qids/class) are NOT
trustworthy for designing a gate — this audit watched the `anchored`-safe
hypothesis invert on a 59-qid held-out. Always validate a gate hypothesis on a
held-out sample distinct from the one that generated it, BEFORE wiring it into
runtime.

## Artifacts

- `bench/end_to_end/reranker_gate_audit.py` (new, devtools — NOT runtime).
- `bench/end_to_end/reranker-gate-1b-result.json` (per-qid class + base/C/gated
  best_rank + verdict; ≤140-char questions only — no haystack raw text).
- Ran under `/tmp/rm-rc-venv` (py3.12 + `[embedding]`). Dataset cache not committed.

See [[project_reranker_alternative]] (1a), [[project_biolocal_retrieval]]
(the gate that DID hold — different regime), [[project_retrieval_ux]].
