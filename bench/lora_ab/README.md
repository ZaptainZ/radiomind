# LoRA A/B — does personal LoRA actually help?

Answer quality comparison between a base Ollama model and a LoRA-adapted model
on the LoCoMo-lite query set. Scores with gold-statement token overlap (no LLM
judge needed).

## Why this matters

P0 audit flagged: training data was tiny + valid=train → any reported loss drop
was memorization. Without an A/B harness, there's no way to know if the LoRA
helps or regresses. This script closes that loop.

## Run

```bash
# 1) Make sure ollama is running and the base model is pulled
ollama pull qwen2.5:0.5b

# 2) Train + deploy the LoRA (once you have 50+ confirmed habits)
radiomind train
radiomind deploy   # registers radiomind-personal in Ollama

# 3) A/B
python bench/lora_ab/eval.py \
    --base qwen2.5:0.5b \
    --lora radiomind-personal \
    --out bench/lora_ab/result.json

# Base-only smoke (no LoRA yet)
python bench/lora_ab/eval.py --base qwen2.5:0.5b
```

## Output

- Per query: retrieved context, base answer, LoRA answer, overlap score
- Aggregate: mean score each side, wins/losses/ties, delta
- **Exit 1 if LoRA mean < base mean - 0.05** (regression gate)

## Scoring

For each query we collect the gold statements (by id) from LoCoMo-lite. Overlap
score is the mean Jaccard-recall of gold tokens present in the model answer,
computed per-CJK-character + per-ASCII-word. It's not a perfect judge but it's
local, free, and consistent — useful for catching regressions even if not for
absolute quality numbers.
