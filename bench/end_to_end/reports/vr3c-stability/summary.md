# stability report

> ⚠ **cross-version envelope** — these runs may be DIFFERENT architecture versions, so mean/std mixes version differences with sampling noise. This is a descriptive envelope, NOT a pure same-architecture run-to-run std. For a true stability std, run k repeats of ONE version and pass --same-arch.

**runs:** 9  |  **mean:** 0.9  **std:** 0.0374  **min:** 0.82  **max:** 0.93  **median:** 0.92
**interpretation:** `cross-version-envelope`

## Runs
| label | score | reported_acc | answer | judge |
|---|---|---|---|---|
| lme-s-n100-v4-deepseek-judge4o.json | 0.82 | 0.82 | deepseek-v3.2 | gpt-4o |
| lme-s-n100-v5-deepseek-judge4o.json | 0.92 | 0.92 | deepseek-v3.2 | gpt-4o |
| lme-s-n100-v6.1.1-deepseek-judge4o.json | 0.93 | 0.93 | deepseek-v3.2 | gpt-4o |
| lme-s-n100-v6.2.2-deepseek-judge4o.json | 0.89 | 0.89 | deepseek-v3.2 | gpt-4o |
| lme-s-v82-1-n100.json | 0.92 | 0.92 | deepseek-v3.2 | gpt-4o |
| lme-s-v822a-n100.json | 0.86 | 0.86 | deepseek-v3.2 | gpt-4o |
| lme-s-v822a-n100.judge-fixed.json | 0.92 | 0.92 | deepseek-v3.2 | gpt-4o |
| lme-s-n100-2026-05-26.json | 0.93 | 0.93 | deepseek-v3.2 | gpt-4o |
| lme-s-n100-2026-06-04-baseline.json | 0.91 | 0.91 | deepseek-v3.2 | gpt-4o |

## Placement (highlighted run)
- `lme-s-n100-2026-06-04-baseline.json` score **0.91** — percentile 33.3  
- Δ vs mean +0.01, Δ vs max -0.02

## Per-qid stability
stable-pass 68 | stable-fail 3 | unstable 29

### Unstable qids (0 < pass_rate < 1, most unstable first)
| qid | qtype | pass_rate | n_pass/n | mode |
|---|---|---|---|---|
| `gpt4_93159ced_abs` | temporal-reasoning | 0.5556 | 5/9 | P |
| `1c0ddc50` | single-session-preference | 0.5556 | 5/9 | P |
| `778164c6` | single-session-assistant | 0.4444 | 4/9 | F |
| `c18a7dc8` | multi-session | 0.4444 | 4/9 | F |
| `bb7c3b45` | multi-session | 0.4444 | 4/9 | F |
| `9ee3ecd6` | multi-session | 0.6667 | 6/9 | P |
| `d851d5ba` | multi-session | 0.6667 | 6/9 | P |
| `b46e15ed` | temporal-reasoning | 0.3333 | 3/9 | F |
| `9aaed6a3` | multi-session | 0.7778 | 7/9 | P |
| `b6025781` | single-session-preference | 0.7778 | 7/9 | P |
| `gpt4_194be4b3` | multi-session | 0.7778 | 7/9 | P |
| `031748ae_abs` | knowledge-update | 0.7778 | 7/9 | P |
| `gpt4_d12ceb0e` | multi-session | 0.7778 | 7/9 | P |
| `d3ab962e` | multi-session | 0.7778 | 7/9 | P |
| `gpt4_8279ba02` | temporal-reasoning | 0.7778 | 7/9 | P |
| `caf9ead2` | single-session-user | 0.8889 | 8/9 | P |
| `e66b632c` | knowledge-update | 0.8889 | 8/9 | P |
| `71017276` | temporal-reasoning | 0.8889 | 8/9 | P |
| `gpt4_f2262a51` | multi-session | 0.8889 | 8/9 | P |
| `09d032c9` | single-session-preference | 0.8889 | 8/9 | P |
| `afdc33df` | single-session-preference | 0.8889 | 8/9 | P |
| `1b9b7252` | single-session-assistant | 0.8889 | 8/9 | P |
| `9a707b82` | temporal-reasoning | 0.8889 | 8/9 | P |
| `6071bd76` | knowledge-update | 0.8889 | 8/9 | P |
| `95228167` | single-session-preference | 0.8889 | 8/9 | P |
| `6aeb4375` | knowledge-update | 0.8889 | 8/9 | P |
| `25e5aa4f` | single-session-user | 0.8889 | 8/9 | P |
| `28bcfaac` | single-session-assistant | 0.8889 | 8/9 | P |
| `gpt4_468eb064` | temporal-reasoning | 0.8889 | 8/9 | P |

## By qtype (mean pass-rate)
- knowledge-update: 0.9653
- multi-session: 0.7901
- single-session-assistant: 0.9542
- single-session-preference: 0.875
- single-session-user: 0.9861
- temporal-reasoning: 0.8431
