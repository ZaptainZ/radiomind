# RerankerAlternative-1a — lightweight local reranker alternatives (offline probe)

**Date:** 2026-06-14
**Author:** Claude Code (cc)
**Type:** READ-ONLY offline experiment. No runtime change, no default-path change,
no cloud, no full benchmark. Probe imports `facet_rerank` helpers read-only (no
modification), so no shared-helper regression needed.
**Question:** Can a lightweight, deterministic, LOCAL rerank approach part of the
2.3GB cross-encoder reranker's benefit — letting the heavy reranker stay an
optional advanced mode instead of the only quality lever above embedding?

## Method

`bench/end_to_end/reranker_alt_probe.py`. Per qid: ingest haystack into a fresh
sandbox domain, embed the full candidate pool with **local on-device ONNX MiniLM**
(REQUIRED baseline — if absent the probe BLOCKS, never falls back to remote), then
rerank the dense top-150 four ways. Gold is turn-level (`has_answer`). 14 curated
qids (BioLocal/target-pack/counting) + 5 controls. Fixed params (not gold-tuned):
alpha .2, lambda .75, beta .5, RRF k 60. Run under py3.12 + `[embedding]` (bench
venv py3.13 can't load ONNX).

- **0 dense baseline** — ONNX cosine ranking.
- **A hubness** — `cos(q,d) − α·mean_sim_to_neighbors(d)` (down-weight "similar to
  everything" generic memories).
- **B MMR** — greedy `λ·rel − (1−λ)·max_redundancy` (embedding cos + same-session/
  role structural penalty).
- **C query-adaptive RRF** — type-weighted RRF fusion of dense / FTS-OR / typed-
  facet / temporal rankings (weights by query class: anchored / temporal-ordering
  / open / cjk). Reuses `facet_rerank` extraction read-only.
- **D graph diffusion** — per-qid bipartite graph (memory ↔ entity/number/session/
  domain/month nodes), 3-step personalized PageRank from query-activated nodes,
  `final = dense + β·graph`.

## Results (19 qids; aggregate)

| method | recall@5 | recall@10 | recall@30 | median best_rank | redundancy@30 | latency_ms |
|---|---|---|---|---|---|---|
| 0 dense baseline | 0.456 | 0.554 | 0.780 | 4 | 0.672 | 0.0 |
| A hubness | 0.471 | 0.564 | 0.780 | 4 | 0.668 | 2 |
| B MMR | 0.480 | 0.541 | 0.759 | 4 | **0.377** | 76 |
| **C query-adaptive RRF** | **0.505** | **0.627** | **0.804** | **2** | 0.604 | 34 |
| D graph diffusion | 0.407 | 0.554 | 0.780 | 4 | 0.681 | 61 |

All methods: `needs_remote=False`; all build on the local ONNX dense base
(`needs_model=True`). Latency is per-qid rerank of ~150 candidates (not a runtime
number — dense embeddings are computed once at ingest in production).

Per-method wins / harms vs dense baseline (best_rank):

- **A hubness** — wins: b46e15ed 25→22, d851d5ba 3→2. harms: c18a7dc8 17→24,
  gpt4_d6585ce8 17→19, 9aaed6a3 14→17. No control harm. Recall essentially flat.
- **B MMR** — wins: c18a7dc8 17→15, b46e15ed 25→10, d851d5ba 3→2, gpt4_7abb270c
  4→3. harms: d3ab962e 12→15, gpt4_d6585ce8 17→26, 9aaed6a3 14→15, **+3 control
  harms** (118b2229 2→3, 58bf7951 4→5, 1e043500 2→4). Redundancy drops hard
  (0.67→0.38) as designed, but recall@10/@30 dip.
- **C query-adaptive RRF** — wins (8): d3ab962e 12→2, 9aaed6a3 14→2, b46e15ed
  25→16, gpt4_d6585ce8 17→12, d851d5ba 3→2, e47becba 4→1, 118b2229 2→1, 1e043500
  2→1. harms (4): **c18a7dc8 17→60**, gpt4_194be4b3 1→5, gpt4_d12ceb0e 1→2,
  58bf7951 4→6 (only one control, minor). Best recall on every cutoff + median
  rank halved.
- **D graph diffusion** — wins: c18a7dc8 17→14, 9aaed6a3 14→11, gpt4_7abb270c 4→3.
  harms: 9ee3ecd6 1→2, b46e15ed 25→26, d851d5ba 3→4, 58bf7951 4→6 (control).
  recall@5 DROPS (0.456→0.407); PPR adds noise more than signal at this scale.

## Verdict per method

- **C query-adaptive RRF → OPEN for 1b runtime-prototype audit, WITH a required
  gate.** Best overall (recall@5 +0.05, @10 +0.07, @30 +0.02, median rank 4→2),
  ≥2 problematic qids strongly improved (d3ab962e 12→2, 9aaed6a3 14→2, plus
  temporal b46e15ed/gpt4_d6585ce8 and controls e47becba/118b2229/1e043500), cheap
  (34ms, no model beyond dense), controls safe except one minor (58bf7951 4→6).
  BUT it HARMS the counting/temporal-precision class (c18a7dc8 17→**60**,
  gpt4_194be4b3 1→5) — the temporal-prior and facet weights inject date/number
  noise there. A runtime version MUST gate those classes (route them to dense-only
  weights), exactly the do-no-harm pattern BioLocal-1b used.
- **B MMR → PARK (conditional).** Real, large redundancy reduction (0.67→0.38) but
  recall@10/@30 dip AND 3 control harms. Only worth pursuing for explicit
  list/aggregation/multi-evidence queries behind a gate; not a general lever.
- **A hubness → PARK.** Marginal (recall@5 +0.015, rest flat); small per-qid
  stores make local density unstable (caveat). Not worth runtime complexity.
- **D graph diffusion → PARK.** recall@5 drops; PPR over sparse per-qid facet
  graphs adds noise. The bb7c3b45 adjacency case it targeted was already solved by
  dense (rank 1). No gain.

## Bottom line

- The most promising lightweight local lever is **query-adaptive RRF (C)** — a
  deterministic, model-free fusion (over the existing dense/FTS/facet/temporal
  signals) that lifts recall into reranker-ballpark territory (+~11% relative
  recall@5) at ~34ms. It is an **OPEN 1b candidate, gated** for the counting/
  temporal class it harms.
- **Local cross-encoder reranker stays the advanced best-quality option.** This
  probe did NOT run a head-to-head against the actual 2.3GB reranker (would need
  the install), so we do NOT claim C replaces it — only that C is a cheap partial
  lever worth a gated runtime audit. Whether reranker can be downgraded to
  optional-heavy needs that direct head-to-head (a future step).
- Embedding remains the prerequisite quality tier (every method builds on dense);
  RetrievalUX-1a's positioning (embedding=recommended, reranker=advanced) stands.

## Artifacts

- `bench/end_to_end/reranker_alt_probe.py` (new, devtools — NOT runtime).
- `bench/end_to_end/reranker-alt-1a-result.json` (full per-qid × method table;
  aggregate metrics + ≤140-char questions + facet fragments only — no haystack
  raw text; safe to commit).
- Ran under `/tmp/rm-rc-venv` (py3.12 + `[embedding]`). Dataset cache not committed.

See [[project_biolocal_retrieval]] (dense is the lever; gating pattern),
[[project_retrieval_ux]] (tier positioning), [[project_managed_retrieval]].
