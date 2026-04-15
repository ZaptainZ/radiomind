# LoCoMo-lite — RadioMind retrieval baseline

A lightweight long-form memory benchmark. 60 factual statements across 6 domains,
50 retrieval queries with gold-standard relevant statement IDs. Output: `Recall@5`
and `Recall@10`.

Intended use:

- Regression gate for retrieval changes (CI fails if Recall@5 < 0.3)
- Apples-to-apples comparison when adding/changing retrieval methods
  (FTS, vector, n-gram LIKE, RRF, HDC habit fusion, etc.)

This is **not** the official LoCoMo dataset — see
<https://github.com/snap-research/locomo> for that. Synthetic data here is
tuned to exercise the retrieval paths RadioMind cares about (CJK dominated,
conversational, mixed preference/fact/event/routine content).

## Run

```bash
# Always sandbox — never touch ~/.radiomind
python bench/locomo_lite/run.py --save bench/locomo_lite/baseline.json

# Per-query detail
python bench/locomo_lite/run.py -v
```

## Current baseline (v0.2, no embedder)

| Metric          | Value  |
|-----------------|--------|
| Recall@5        | ~0.71  |
| Recall@10       | ~0.73  |
| Latency / query | < 1 ms |
| Retrieval path  | CJK-n-gram LIKE + RRF; FTS misses on CJK due to unicode61 tokenizer |

With the embedding model installed (`pip install radiomind[embedding]`), vector
search kicks in via RRF fusion and the semantic misses (e.g. "职业" → "iOS 开发
工程师") should close.
