"""Mem0 evaluation protocol — verbatim copy for apples-to-apples comparison.

Source: https://github.com/mem0ai/memory-benchmarks (Apache 2.0)
Fetched: 2026-04-17

These files are copied UNCHANGED from the Mem0 benchmarks repo so that when
we run RadioMind through the same harness prompts, any score difference is
attributable to the memory system itself, not prompt engineering.

Files:
- longmemeval_prompts.py — answer + judge for LongMemEval S (session-level)
- locomo_prompts.py      — answer + judge for LoCoMo (multi-session dialogues)
- beam_prompts.py        — answer + judge for BEAM (production-size evals)

Mem0 v3 reference numbers (from their README, 2026-04):
- LoCoMo        91.6   (vs previous 71.4)
- LongMemEval   93.4   (vs previous 67.8)
- BEAM (1M)     64.1
- BEAM (10M)    48.6

MemMachine reference numbers (arxiv 2604.04853, 2026-04):
- LoCoMo            0.9169  (gpt-4.1-mini)
- LongMemEvalS      0.930   (6-dim ablation, gpt-5-mini)

Both use their own lenient judge rubrics (not a single-line "CORRECT/INCORRECT"
question). Our earlier LongMemEval 0.725 used a much stricter judge and the
"oracle" dataset (1.9 sessions/q) instead of "_s_cleaned" (47.7 sessions/q) —
that number is NOT comparable to published Mem0/MemMachine results.
"""
