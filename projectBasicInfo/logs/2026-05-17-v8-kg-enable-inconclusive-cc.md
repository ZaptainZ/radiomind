# 2026-05-17 V8 KG-Enable 尝试 — 跨次不稳定，未能确认改进

## 背景

V7 fullans 3-run strict 稳定 5/10。Codex 审查指出 stable FAIL 4 题里 c4 Seattle / c5 Voyageurs 是 retrieve 漏召问题。诊断证实：

- c4 Seattle: 对话里 D3:19 明确含 "It's Seattle, I'm stoked for my game there"
- V7 fullans retrieve top-200 完全没召回该 memory（vec+FTS+like 都漏）
- V6.3 baseline 当时 c4 PASS — 关键差异是 **V6.3 启用了 KG batch，V7 fullans 用 `RADIOMIND_DISABLE_KG_BATCH=1` 规避了之前的 DashScope hang**

## V8 假设

启用 KG batch + refinement，让 KG entity 层（John → plays_in → Seattle）surface c4 gold-bearing memory。

## 实测

### Run 1（合并 3 个 checkpoint，1.5 hour timeout + 2 次 resume）

| qid | raw | strict |
|---|:---:|:---:|
| c1 Gina | P | P |
| c2 financial | F (ans SSL) | F |
| c2 Maria | P | P |
| c3 count | P | F (orig 接受 "3"，strict 严判 vs gold "two") |
| c3 Tilly | F→P (retry) | P |
| c3 Nate | F | F |
| **c4 Seattle** | **P** ★ | **P** ★ |
| c5 Voyageurs | F (gold-impossible) | F |
| c6 Sept 2022 | P | P |
| c9 Calvin | P | F (orig PASS 但答 "encouragement"，strict 缺 hard work) |

V8 run 1: raw 7/10, **strict 5/10**。

### Run 2（fresh sandbox）

| qid | raw | strict |
|---|:---:|:---:|
| c1 Gina | F (committed 2023-02-08) | F |
| c2 financial | F (ans SSL) | F |
| c2 Maria | F (ans SSL) | F |
| c3 count | F (ans SSL) | F |
| c3 Tilly | F | F |
| c3 Nate | F | F |
| **c4 Seattle** | **F (committed Minneapolis)** | **F** |
| c5 Voyageurs | F (ans SSL) | F |
| c6 Sept 2022 | n/a (timeout) | n/a |
| c9 Calvin | n/a (timeout) | n/a |

V8 run 2: raw **0/8**, strict **0/8**。

## 结论：V8 KG-enable 跨次不稳定

两次独立 run 的 c4 Seattle 翻牌（run 1 PASS via KG，run 2 FAIL committed Minneapolis）。原因诊断：

1. **KG batch LLM 抽取非确定性**：每次 ingest LLM 输出不同 triples，导致 KG entity 层 surface 不同 candidates
2. **DashScope answer LLM SSL 不稳定**：run 2 有 4/10 answer SSL fail，环境性问题
3. **Refinement 开启加长流程**：每题更多 LLM call，SSL 暴露面更大

**V8 真实成绩**：~0-5/10 strict，与 V7 fullans 5/10 baseline 无统计可信优势。

## 决策

放弃 V8 KG-enable 方向。理由：

- KG 抽取本身需要 LLM 调用（用 deepseek-v3.2），引入 ingest-time 不确定性
- 该不确定性 → KG triple 不同 → retrieve candidate 不同 → c4 类题翻牌
- 即使 KG 抽到正确 triple，refinement 流程长 → SSL fail 概率高 → 净收益不显著

## 与 V7 fullans 真实对照

| 版本 | strict 稳定值 | 备注 |
|---|---|---|
| V6.3 baseline | 4/10 (单次) | KG + refinement enabled 但只测过一次 |
| V7 fullans | 5/10 (3-run avg) | KG/refinement disabled，evidence-candidate injector 替代 |
| V8 KG-enable | inconclusive | 跨次翻牌，环境 SSL 不稳 |

V7 仍是最稳定的可测改进 = **+1 over V6.3 baseline**。

## V8 真正应该攻击的方向（重新规划）

按 Codex 建议 + V7+V8 实测教训：

### V8.1 候选: candidate commit hardening（不依赖 KG）

V7 的 3 题 67% rotating（c1 Gina/c3 Nate/c6 Sept）是：candidate 已 salient，但 LLM commit 阶段被 instinct 拉走。修：

- **更强 ordering instruction**：evidence block 头部加 "MUST commit to the highest-confidence candidate marked with [primary=true]"
- **commit anchor**：candidate 旁边给 explicit "commit_reason" 字段，引导 LLM 推理链不漂移
- **temporal_role 强制**：当 gold 是 relative phrase 时，prompt 显式禁止 commit absolute date

### V8.2 候选: retrieve 层 reverse-FTS (不依赖 KG)

针对 c4 Seattle 这种 "答案在 memory 里但不在 query 字面" 的情况：

- 当 query 是 "which city/place/X" 类型时，对所有 candidate memory 做 entity extraction
- 对提取出的 entities 做 BM25 boost
- 这避开 KG 抽取的不确定性

### V8.3 候选: reasoning-aware candidates (c2 financial / c3 count)

- c3 count：需要 dedup ordinal "third"→2。增加 candidate level 的 dedup 信号
- c2 financial：需要 aspect-aware（wealth-class vs current-stress）。增加 "abstract state aggregation" candidate type

## 现状

- V7 fullans = 5/10 strict 仍是最稳基线
- V8 KG-enable 不稳定，不推进
- V8.1/.2/.3 待选

## 文件

```
bench/end_to_end/validation/v8-kg-flip10.combined.json    # V8 run 1 raw 7, strict 5
bench/end_to_end/validation/v8-kg-flip10.run2.json        # V8 run 2 raw 0/8, strict 0/8
```
