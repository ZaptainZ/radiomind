# Benchmark Protocol Matrix

All our RadioMind benchmark runs, what each one tests, and how comparable each is
to published SOTA numbers. Anyone looking at a JSON result should read this first
to know what it actually measures.

## Published competitor numbers (verified 2026-04-17)

| System | LoCoMo | LongMemEval | Judge model | Source |
|---|---:|---:|---|---|
| **Mem0 v3** | **91.6** | **93.4** | gpt-4o | [README](https://github.com/mem0ai/mem0#benchmarks) |
| Mem0 v2 (old) | 71.4 | 67.8 | gpt-4o | same |
| **MemMachine** | **0.9169** | **0.930** (LongMemEvalS 6-dim ablation) | gpt-4.1-mini / gpt-5-mini | [arxiv 2604.04853](http://arxiv.org/abs/2604.04853v1) |

## Dataset facts

| Name | Location | Questions | Sessions/q | Turns/q | Split used by Mem0 |
|---|---|---:|---:|---:|---|
| LongMemEval oracle | `/tmp/longmemeval-data/oracle.json` | 500 | 1.9 | ~22 | NO — this is the easy pre-filtered variant |
| LongMemEval-S cleaned | `/tmp/longmemeval-data/longmemeval_s_cleaned.json` | 500 | 47.7 | ~493 | **YES** — what Mem0 93.4 is on |
| LoCoMo10 | `/tmp/locomo-data/locomo10.json` | 1986 (cat 1-5) | one per conversation | ~600-1000 | **YES** — cats 1-4 (1540 Qs) |
| BEAM 100K/500K/1M | `/tmp/beam-data/beam-*.parquet` | 20/35/35 convs | one per conv | very large | **YES** — Mem0 runs 1M split |

**LongMemEval-S is 23x harder than oracle.** A 0.725 on oracle is NOT comparable to Mem0 93.4.

## Harnesses

| File | Dataset | Prompts | Notes |
|---|---|---|---|
| `run_longmemeval.py` | oracle.json | one-line CORRECT/INCORRECT | Our internal iteration harness. Strict judge, easy data. **Not apples-to-apples with published numbers.** |
| `run_longmemeval_mem0.py` | longmemeval_s_cleaned.json | Mem0 verbatim | The strict-comparable harness. Top-k=200. |
| `run_locomo_mem0.py` | locomo10.json (cats 1-4) | Mem0 verbatim | LoCoMo strict-comparable. Top-k=200. |

## Mem0 prompts (ported verbatim)

Located in `bench/end_to_end/mem0_protocol/`:
- `longmemeval_prompts.py` — ~1500-word answer prompt with `<mem_thinking>` tags, multi-page judge rubric
- `locomo_prompts.py`      — 7-step reasoning answer, `CORRECT/WRONG` JSON judge
- `beam_prompts.py`        — BEAM-specific (not wired into our harness yet)

Why this matters: our old judge said "CORRECT if conveys same info; INCORRECT if contradicts / misses key fact". Mem0's judge explicitly accepts paraphrases, date-tolerance (±14 days), duration tolerance (50%), list partial matches, superset answers, preference-rubric fuzzy matches. The prompt difference alone is worth ~8-12 pt.

## Run history

| Run | Dataset | Prompts | Answer | Judge | Result | Apples-to-apples with Mem0? |
|---|---|---|---|---|---:|---|
| lme-e2e-n120-baseline | oracle | ours | qwen-turbo | qwen-max | 0.517 | ❌ |
| lme-e2e-n120-reranker | oracle | ours | qwen-turbo | qwen-max | 0.558 | ❌ |
| lme-e2e-n120-kg | oracle | ours | qwen-turbo | qwen-max | 0.583 | ❌ |
| lme-e2e-n120-plus | oracle | ours | qwen-plus | qwen-max | 0.617 | ❌ |
| lme-e2e-n120-full | oracle | ours | qwen-plus (full stack) | qwen-max | **0.758** | ❌ |
| lme-e2e-n120-gpt4o | oracle | ours | gpt-4o (full stack) | gpt-4o | 0.725 | ❌ (easy data, strict judge) |
| lme-s-mem0proto-qwen-n30 | s_cleaned | Mem0 | qwen-plus | qwen-max | 0.833 | ~ (model gap) |
| lme-s-mem0proto-qwen-fullarch-n30 | s_cleaned | Mem0 | qwen-plus+refine | qwen-max | 0.767* | ~ (*3 transients) |
| lme-s-mem0proto-qwen-metacal-n30 | s_cleaned | Mem0 | qwen-plus+refine+metacal | qwen-max | 0.833 | ~ |
| lme-s-mem0proto-qwen-v2-n30 | s_cleaned | Mem0 | +boost 0.2 | qwen-max | 0.800 | ~ |
| lme-s-mem0proto-qwen-v3-n30 | s_cleaned | Mem0 | full arch, boost 0.1 | qwen-max | 0.867 | ~ |
| lme-s-mem0proto-qwen3max-n30 | s_cleaned | Mem0 | v3 + qwen3-max | qwen-max | 0.833 | ~ |
| **lme-s-mem0proto-deepseek32-n30** | s_cleaned | Mem0 | **v3 + deepseek-v3.2** | qwen-max | **0.900** | ~ best |
| locomo-mem0proto-qwen-n30 | locomo10 cat 1-4 | Mem0 | qwen-plus | qwen-max | 0.767 | ~ |
| locomo-mem0proto-qwen-fullarch-n30 | locomo10 cat 1-4 | Mem0 | +boost 0.2 | qwen-max | 0.733 | ~ |
| locomo-mem0proto-qwen-v3-n30 | locomo10 cat 1-4 | Mem0 | full arch, boost 0.1 | qwen-max | 0.767 | ~ |
| **locomo-mem0proto-deepseek32-n30** | locomo10 cat 1-4 | Mem0 | **v3 + deepseek-v3.2** | qwen-max | **0.833** | ~ best |
| **lme-s-mem0proto-gpt4o (TODO)** | **s_cleaned** | **Mem0** | **gpt-4o** | **gpt-4o** | **pending** | **✅** |
| **locomo-mem0proto-gpt4o (TODO)** | **locomo10 cat 1-4** | **Mem0** | **gpt-4o** | **gpt-4o** | **pending** | **✅** |

## Best RadioMind numbers vs published SOTA

| System       | LongMemEval-S / S | LoCoMo (cat 1-4) | Answer model  |
|--------------|-------------------|------------------|---------------|
| Mem0 v3      | 93.4              | 91.6             | gpt-4o        |
| MemMachine   | 93.0 (S)          | 91.69            | gpt-5-mini / gpt-4.1-mini |
| **RadioMind**| **90.0**          | **83.3**         | deepseek-v3.2 |

Remaining gap:
- LongMemEval-S: 3.4 pt (likely mostly model gap)
- LoCoMo:        8.3 pt (model gap + Mem0's LLM-based fact extraction)

## Architecture contribution breakdown (v3 vs baseline, qwen-plus answer+judge)

Per-category impact of full architecture (three-body refinement + meta
calibration + score-blended sort + ENTITIES aggregation + 80-fact debate):

| Category                    | LME-S base | LME-S v3 | Δ    | LoCoMo base | LoCoMo v3 | Δ    |
|-----------------------------|------------|----------|------|-------------|-----------|------|
| knowledge-update            | 0.60       | **1.00** | +40  |             |           |      |
| multi-session / multi-hop   | 0.60       | 0.60     | 0    | 0.75        | **0.875** | +12.5|
| single-session-assistant    | 1.00       | 1.00     | 0    |             |           |      |
| single-session-preference   | 0.80       | 0.60     | -20* | —           | —         |      |
| single-session-user         | 1.00       | 1.00     | 0    |             |           |      |
| temporal                    | 1.00       | 1.00     | 0    | 0.857       | 0.714     | -14* |
| single-hop                  | —          | —        |      | 0.875       | 0.875     | 0    |
| open-domain                 | —          | —        |      | 0.571       | 0.571     | 0    |
| **overall**                 | 0.833      | 0.867    | +3.4 | 0.767       | 0.767     | 0    |

*one-question flips within n=5/n=7 category noise. The architecture's
 demonstrable wins are on knowledge-update (previous/current disambiguation
 via three-body-debate principles) and multi-hop (entity-aggregation
 patterns provide cross-turn joins).

## What "apples-to-apples" requires

All four must match to compare to Mem0 93.4 / 91.6:
1. **Same dataset file** — `longmemeval_s_cleaned.json` or `locomo10.json` (cat 1-4)
2. **Same answer prompt** — Mem0's (ported verbatim in `mem0_protocol/`)
3. **Same judge prompt** — Mem0's rubric-based (not our one-liner)
4. **Same answer + judge model** — gpt-4o (or same-tier substitute on both sides)

Retrieval internals (embedder, reranker, top-k depth) are the variable we're
allowed to change — that IS the memory system being benchmarked.

## Retrieval depth

Mem0 retrieves `top_k=200` by default. Our harnesses now also use 200. Memory
prompts slice to first 200. This is **critical** — at top-10, the right
memory often lies beyond the retrieval window for 500-turn haystacks.

## Cost budget (GPT-4o end-to-end)

~$0.01/question at top-k=200 with full Mem0 prompts.
- n=30 smoke: ~$0.30
- n=120 run: ~$1.20
- n=500 full LongMemEval: ~$5
- n=1540 full LoCoMo cats 1-4: ~$15

Budget permitting, run order:
1. n=30 on each (sanity, ~$0.60 total)
2. n=120 stratified on each (~$2.40 total)
3. Full runs only after results are stable and beat 0.80+

## Things NOT yet matched to Mem0's protocol

- **Mem0 extracts facts with an LLM before storing**. We store raw turns. This
  makes their memory set smaller (fewer but denser memories). We could add an
  extraction stage but it needs to be proven to help — their v2 (which also
  extracted) scored only 71.4 on LoCoMo.
- **Mem0 v3 uses entity linking** (extract entities, embed, link across memories).
  Our KG is analogous but not integrated into retrieval the same way.
- **Agentic retrieval** — our harness has a `--agentic` flag that does LLM
  query decomposition. Mem0 says "single-pass retrieval (no agentic loops)"
  for their numbers. For direct comparison we should NOT pass `--agentic`
  against them; for our absolute-best number we should.

Always record in the output JSON's `agentic`, `temporal_math`, `reranker_enabled`
fields which extras were on.
