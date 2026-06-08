# stability report

> **same-arch stability** (caller-asserted) — inputs are repeats of one architecture version; mean/std approximates run-to-run sampling noise. NB: --same-arch is an annotation, not a verified fact.

**runs:** 3  |  **mean:** 0.91  **std:** 0.01  **min:** 0.9  **max:** 0.92  **median:** 0.91
**interpretation:** `same-arch-stability`

## Runs
| label | score | reported_acc | answer | judge |
|---|---|---|---|---|
| lme-s-n100-2026-06-04-baseline.json | 0.91 | 0.91 | deepseek-v3.2 | gpt-4o |
| lme-s-n100-2026-06-06-run2.judge-fixed.json | 0.92 | 0.92 | deepseek-v3.2 | gpt-4o |
| lme-s-n100-2026-06-06-run3.json | 0.9 | 0.9 | deepseek-v3.2 | gpt-4o |

## Placement (highlighted run)
- `lme-s-n100-2026-06-04-baseline.json` score **0.91** — percentile 33.3  
- Δ vs mean +0.0, Δ vs max -0.01

## Per-qid stability
stable-pass 86 | stable-fail 5 | unstable 9

### Unstable qids (0 < pass_rate < 1, most unstable first)
| qid | qtype | pass_rate | n_pass/n | mode |
|---|---|---|---|---|
| `gpt4_9a159967` | temporal-reasoning | 0.6667 | 2/3 | P |
| `gpt4_f2262a51` | multi-session | 0.6667 | 2/3 | P |
| `b46e15ed` | temporal-reasoning | 0.6667 | 2/3 | P |
| `9a707b82` | temporal-reasoning | 0.6667 | 2/3 | P |
| `c18a7dc8` | multi-session | 0.6667 | 2/3 | P |
| `35a27287` | single-session-preference | 0.6667 | 2/3 | P |
| `9ee3ecd6` | multi-session | 0.3333 | 1/3 | F |
| `gpt4_194be4b3` | multi-session | 0.3333 | 1/3 | F |
| `778164c6` | single-session-assistant | 0.3333 | 1/3 | F |

## By qtype (mean pass-rate)
- knowledge-update: 1.0
- multi-session: 0.7778
- single-session-assistant: 0.9608
- single-session-preference: 0.8542
- single-session-user: 1.0
- temporal-reasoning: 0.8824
