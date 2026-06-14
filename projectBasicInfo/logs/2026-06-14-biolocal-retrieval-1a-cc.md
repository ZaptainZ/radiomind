# BioLocalRetrieval-1a — local bio-inspired retrieval feasibility (offline probe)

**Date:** 2026-06-14
**Author:** Claude Code (cc)
**Type:** READ-ONLY offline experiment. No runtime change, no default-path change,
no cloud retrieval service, no n=100 full benchmark, no new user data uploaded.
**Question:** Can local structured / bio-inspired retrieval approach remote
embedding/rerank — i.e. is a cloud vector service a *necessary* capability, or a
convenience?

## Method

New probe `bench/end_to_end/biolocal_probe.py` (not in runtime). For each curated
qid: ingest the haystack into a throwaway sandbox domain, then score FOUR tiers
over the **full candidate pool** and measure gold-evidence rank/coverage at
**turn level** (dataset `has_answer` flag — stricter than the session-level signal
earlier diagnostics used):

- **A** FTS/BM25 only (current local default; `mind.search` with the embedder
  detached so it cannot silently route to vector).
- **B** FTS + typed facets — deterministic overlap bonuses: number/amount,
  Title-Case/brand entity, content-bigram phrase, role==user, session-month.
  Fixed documented weights (not gold-tuned): num .40 / ent .30 / phrase .25 /
  role .08 / time .10.
- **C** B + HDC — deterministic ±1 bipolar hypervector (dim 4096) superposed over
  the facet atoms; cosine association bonus (w .35).
- **D** local **on-device** ONNX MiniLM-384 semantic similarity (upper bound).
  **Not remote** — the remote embedder is NOT called (it would need consent +
  upload; deferred per ManagedRetrieval-1b). Run under a py3.12 venv because the
  bench venv's py3.13 has broken pyexpat (the recurring trap) so the embedder
  won't install there.

Dataset `longmemeval_s_cleaned.json` (277 MB, public HuggingFace, user-authorized
re-download — the cache had been cleared). 14 curated target qids (counting
cluster, bb7c3b45, ordering, target-pack lines) + 5 do-no-harm controls.

> **Experiment bug caught & fixed mid-run:** when the embedder is loaded,
> `mind.search()` auto-routes to vector (knn), which contaminated the FTS baseline
> (A looked like median-rank 4). Forcing `mind._embedder=None` for A/B/C restored
> true FTS (median 119); D uses the standalone embedder ref directly. The final
> artifact's A/B/C reproduce the embedder-absent py3.13 run exactly.

## Results (best_rank / hits@30 / gold_total; ∞ = gold never retrieved)

| qid | type | A FTS | B facets | C HDC | D local-sem |
|---|---|---|---|---|---|
| 9ee3ecd6 | multi-session | 40/0/2 | **1/2** | 1/2 | 1/2 |
| gpt4_194be4b3 | multi-session | 119/0/4 | 85/0 | 223/0 | **1/2** |
| d3ab962e | multi-session | 119/0/2 | 67/0 | 219/0 | **12/2** |
| c18a7dc8 | multi-session | 168/0/2 | 107/0 | 141/0 | **17/1** |
| b46e15ed | temporal | 6/**3**/5 | 14/1 | 14/1 | 25/1 |
| bb7c3b45 | multi-session | 54/0/2 | **5/2** | 7/2 | 1/2 |
| gpt4_d6585ce8 | temporal | 10/1/5 | 44/0 | 42/0 | **17/2** |
| 031748ae_abs | knowledge-update | ∞ (gold_total=0, abstain qid) | | | |
| gpt4_93159ced_abs | temporal | ∞ (gold_total=0, abstain qid) | | | |
| gpt4_93159ced | temporal | 192/0/3 | **3/3** | 2/3 | 1/2 |
| 9aaed6a3 | multi-session | 403/0/2 | **1/2** | 1/2 | 14/2 |
| gpt4_d12ceb0e | multi-session | 198/0/3 | 107/0 | 91/0 | **1/3** |
| d851d5ba | multi-session | 134/0/4 | **13/1** | 14/1 | 3/4 |
| gpt4_7abb270c | temporal | 43/0/6 | **26/1** | 19/1 | 4/3 |
| e47becba (ctrl) | single-session | 19/**2**/2 | 10/1 | 143/0 | 4/1 |
| 118b2229 (ctrl) | single-session | 397/0/1 | **17/1** | 17/1 | 2/1 |
| 51a45a95 (ctrl) | single-session | 85/0/1 | **1/1** | 1/1 | 1/1 |
| 58bf7951 (ctrl) | single-session | 293/0/1 | 151/0 | 149/0 | **4/1** |
| 1e043500 (ctrl) | single-session | 1/1/1 | 1/1 | 1/1 | 2/1 |

**Aggregate (17 scored qids; 2 abstain qids have no gold):**

| tier | median best_rank | mean recall@30 | in_top30 | needs LLM | needs remote |
|---|---|---|---|---|---|
| A FTS | 119 | 0.147 | 4/19 | no | no |
| B facets | 17 | 0.427 | 11/19 | no | no |
| C HDC | 19 | 0.401 | 10/19 | no | no |
| **D local-semantic** | **4** | **0.698** | **17/19** | no | **no (on-device)** |

Latency: A/B/C ≈ sub-ms–low-ms per qid (deterministic); D ≈ 40 s/qid here only
because the probe encodes every candidate one-by-one (a real index encodes once
at ingest — not a production latency signal).

## Findings

1. **The dominant quality lever is a LOCAL embedder, and it is NOT cloud.**
   D (on-device ONNX MiniLM, already shipped as `pip install radiomind[embedding]`)
   lifts recall@30 from FTS's 0.147 to **0.698** and best-rank median 119→4, fully
   offline, no upload. → **Cloud/remote vector is NOT a necessary capability for
   quality.** This empirically validates ManagedRetrieval-1a's PARK of the hosted
   vector product: remote embedding/rerank is a *convenience* (cross-device, zero
   local compute, no 86 MB model), correctly gated behind consent (1b), not a
   quality requirement.

2. **Typed facets (B) close ~half the FTS→semantic gap, cheaply, with no model.**
   recall 0.147→0.427, in_top30 4→11. Big wins where the gold turn was lexically
   diluted/pushed out: 9ee3ecd6 40→1, bb7c3b45 54→5 (driven by entity
   "jimmy choo" + bigram + role + month, not numbers), gpt4_93159ced 192→3,
   9aaed6a3 403→1, 51a45a95 85→1, 118b2229 397→17. This matters specifically for
   the **bare-install FTS-only floor** (users who don't install the embedder).

3. **Facets are NOT safe as a blanket boost — they harm two cohorts.**
   (a) temporal-reasoning qs where FTS lexical match was already good:
   b46e15ed A 3hits→B 1hit, gpt4_d6585ce8 A 1hit→B 0hit. (b) a control where FTS
   had full coverage: e47becba A 2/2 → B 1/2. Number/date facets create spurious
   overlaps on temporal qs. → a facet re-rank must be **query-type-gated**, not global.

4. **HDC (C) shows NO independent gain and adds noise — drop it.**
   C 0.401 < B 0.427; it actively regresses several qids (gpt4_194be4b3 85→223,
   d3ab962e 67→219, e47becba 10→143). This deterministic superposition prototype
   does not beat plain facet overlap. No ≥2-mechanism benefit from HDC.

5. **The counting cohort's retrieval floor is SEMANTIC, not structural.**
   Of the 5 counting/temporal-unstable qids, 3 (gpt4_194be4b3, d3ab962e, c18a7dc8)
   are recovered into top-30 **only by D** — facets can't (the evidence is
   paraphrase-similar, not token/number-overlapping). b46e15ed is best under plain
   FTS. This is concrete evidence for why the counting cluster was PARKED under
   FTS-only: its gap is semantic recall, which a *local* embedder addresses.

## Decision-tree mapping

- "≥2 problematic qids improved AND stable-pass unharmed → OPEN 1b": **partially.**
  B improves many problematic qids, but stable/temporal cases ARE harmed →
  OPEN 1b **only with query-type gating**, not a blanket boost.
- "B/C ≈ D → cloud not necessary": B/C do **not** reach D (0.43 vs 0.70). But D is
  itself **local** → **cloud is still not necessary**; the local embedder is the
  ceiling. Stronger conclusion than the branch anticipated.
- "improvement single-qid → PARK": no, improvement is broad.

## Verdict & recommendation

- **Cloud vector is a convenience, not a necessity.** Ship/encourage the **local
  ONNX embedder** (`[embedding]` extra) as the primary quality lever; it already
  exists and wins. Remote stays consent-gated (1b) for cross-device / zero-compute
  users. **Confirms 1a PARK.**
- **OPEN BioLocalRetrieval-1b — NARROW:** a query-type-gated **facet re-rank
  applied on top of FTS only when no embedder is present**, to lift the
  bare-install FTS floor for number/entity-anchored multi-session qs, behind a
  strict do-no-harm gate (never apply to temporal-reasoning or
  already-fully-covered queries). Strictly local, no model, no cloud. This is the
  only defensible runtime step; it helps exactly the users who skip the embedder.
- **DROP HDC** from scope (no gain, adds noise).
- **Do NOT** build cloud vector, treat facets as a global boost, or pursue HDC.

## Artifacts

- `bench/end_to_end/biolocal_probe.py` (new, devtools-side, NOT runtime).
- `bench/end_to_end/biolocal-1a-result.json` (full A/B/C/D table — milestone
  decision artifact, kept visible).
- Dataset re-fetched to `~/Library/Caches/radiomind-data/` (public, cache restore).
- D ran under `/tmp/rm-rc-venv` (py3.12 + `[embedding]`); bench venv py3.13 can't
  install the embedder (broken pyexpat).

See [[project_managed_retrieval]] (1a/1b), [[project_lme_s_fail_families]]
(retrieval-reliability is the pass lever), [[project_host_llm_assumed]].
