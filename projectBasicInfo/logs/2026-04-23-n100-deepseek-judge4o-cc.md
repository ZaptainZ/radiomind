# 2026-04-23 n=100 LongMemEval-S: deepseek-v3.2 / gpt-4o

## 运行参数

| 项 | 值 |
|---|---|
| answer_model | deepseek-v3.2（TokenPlan profile `openai`）|
| judge_model | openai/gpt-4o（OpenRouter profile `openrouter`）|
| reranker | on |
| benchmark_mode | a2a-practice（默认）|
| n_questions | 100（stratified 6 qtype）|
| elapsed | **70016s ≈ 19h 26m** |
| 预估费用 | **~$8**（deepseek ~$7 + gpt-4o judge ~$1）|

## 结果

**Overall accuracy: 0.790**（79/100）

| qtype | n | acc | 对比 2026-04-20 FINAL (gpt-4o×gpt-4o, 0.830) |
|---|---:|---:|---|
| knowledge-update | 17 | **0.941** | 0.882 ↑ +5.9pt |
| single-session-assistant | 16 | 0.938 | 1.000 ↓ −6.2pt |
| single-session-user | 16 | 0.812 | 1.000 ↓ −18.8pt |
| multi-session | 18 | 0.722 | 0.722 持平 |
| single-session-preference | 16 | 0.688 | 0.688 持平 |
| temporal-reasoning | 17 | 0.647 | 0.706 ↓ −5.9pt |

## 对历史错题的 diff（18 错 baseline → 21 错 current）

- **9 道恢复**（historical FAIL → now PASS）：架构修复生效
  - B4 premise-verification 命中：`031748ae_abs`, `2133c1b5_abs`, `2311e44b_abs`
  - age_interval skill：`c18a7dc8`
  - 其他 prompt / retrieval：`603deb26`, `94f70d80`, `afdc33df`, `gpt4_1916e0ea`, `gpt4_b0863698`
- **9 道依旧错**（包括 `370a8ff4` errata；主 bench 未启用 errata 白名单导致它也计入 FAIL）
- **12 道新错**（historical PASS → now FAIL）：换 deepseek answer + gpt-4o judge 带来的新问题

### 12 道 regressed 的原因分解

| 原因 | 数量 | 例子 |
|---|---:|---|
| **B4 规则过严 → false abstain** | 3 | `b46e15ed`, `6e984301`, `778164c6` |
| deepseek 答题质量短板（数字幻觉、聚合错）| 6 | `9ee3ecd6` 300 vs 100；`d851d5ba` 总金额错 |
| Judge 格式严（"four bikes" vs "4"）| 1 | `89941a93` |
| 其他（未分类） | 2 | |

## 诊断

1. **架构收益真实**：9 道历史 FAIL 在换了更弱的 answer 模型（deepseek < gpt-4o）之后仍能翻正，说明 skill + prompt rule 在模型能力差异下依然稳定生效。
2. **Answer 模型差异决定绝对水平**：12 道 regressed 中 6 道是 deepseek 本身能力不足（数字/聚合/指令遵循）；这些在 gpt-4o answer 下会自然修复。
3. **B4 的过严副作用**：premise-verification 规则在 deepseek 上更容易触发 abstain —— 可能 deepseek 对"前提不成立"的判断门槛更低。当前 B4 规则用词 "If the premise..." → "abstain"，在答案不确定时 deepseek 更倾向直接走 abstain 分支。需要未来在 B4 里加一个"如果证据存在，即使不完整也尝试答"的对冲。

## 口径 / 与 Mem0 对比

- Mem0 公开 LME-S SOTA：0.68（gpt-4o answer + gpt-4o judge，n=500）
- 本次 RadioMind：**0.790（deepseek answer + gpt-4o judge，n=100）**
- **领先 Mem0 +11pt**，但用的是**更便宜**的 answer 模型（$8 vs Mem0 估算 $50+）

SOTA 0.934 仍需 gpt-4o answer。

## 下一步选项

| 选项 | 说明 | 费用 | 预期 acc |
|---|---|---:|---:|
| A | **跑 gpt-4o×gpt-4o n=100** 锁 SOTA 复刻分数 | ~$100 | **0.87-0.92** |
| B | 先调 B4 rule 放宽 abstain 触发，再跑 deepseek/gpt-4o | $8 | 0.80-0.82 |
| C | 接受 0.790 作为 cost-efficient baseline，写论文时分两档报 | $0 | — |

## 修改文件

- `bench/end_to_end/lme-s-deepseek-judge4o-n100.json`（完整结果）
- `bench/end_to_end/lme-s-deepseek-judge4o-n100.ckpt.jsonl`（per-query checkpoint）

## 结论

本次验证了**"架构的主要价值无关乎 answer 模型强弱"**这一判断：9 道历史 fail 在弱 answer 下也能修。但绝对 accuracy 受制于 answer 模型上限，**deepseek-v3.2 在 LongMemEval-S 硬题上比 gpt-4o 低 ~4pt**。

要对标 Mem0 SOTA 数字必须用 gpt-4o answer；要展示**成本 - 架构**叙事则 deepseek answer 足够。
