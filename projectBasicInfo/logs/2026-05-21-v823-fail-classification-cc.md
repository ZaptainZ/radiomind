# 2026-05-21 V8.2.3 完整 FAIL 分类 — Codex 4 列框架

## 起因

V8.2.3 retrieval expansion 前提被证伪（`9a707b82` / `9aaed6a3` 的 gold evidence 已在 V8.2.1 retrieve top-K 内）。Codex 提议：先做完整 FAIL 分类，按"evidence 已在 + computation deterministic + trigger 窄"准则筛 helper。

## V8.2.1 LME-S n=100 真实 FAIL（8 题）

V8.2.1 原报 92/100，0 judge errors，故 8 题真 FAIL（其中 `031748ae_abs` 已被 V8.2.2b 解决）。

## 4 列分类（手工诊断）

| qid | retrieve top-K 含 gold/evidence | answer 行为 | needs computation | safe helper? |
|---|---|---|---|---|
| **9aaed6a3** SaveMart $0.75 | rank 1-3 含 "$75 spent" + "1% cashback" 链 | ABSTAIN | cashback rate × amount | **YES（窄+决定性）** |
| ~~031748ae_abs~~ Engineer Manager | n/a (V8.2.2b 已解决) | n/a | n/a | n/a |
| **d851d5ba** 慈善总额 $3,750 | 多个 donation events scattered | COMMIT 错 sum | 多项求和 | MAYBE (risk: 误算/缺项) |
| **gpt4_d12ceb0e** 平均年龄 59.6 | 多人年龄可能不全在 memory | ABSTAIN | average | NO（数据不全） |
| **9a707b82** chocolate cake | rank **4** "baked chocolate cake for friend's birthday last weekend" | ABSTAIN | temporal soft-match | YES（窄+hint-only） |
| **gpt4_d6585ce8** 演唱会顺序 | 多个 event 含日期 | COMMIT 错 order | 时间排序 | MAYBE (risk) |
| **gpt4_ab202e7f** 厨房物品 5 | 多个 item events scattered | COMMIT 错 count | count + dedup | MAYBE (risk) |
| **d6233ab6** 重逢建议 | preference 层 | ABSTAIN | 无 | NO（preference, not deterministic） |

## 按 Codex 准则筛选

只推进满足全部三个条件的题：
1. evidence 已在 retrieve top-K
2. 推理能用 deterministic helper 表达
3. trigger 很窄

### Tier 1 (最低风险，强烈推荐做)

**V8.2.3a: cashback arithmetic helper（target: 9aaed6a3）**

- Trigger 模式: question 含 "how much" + ("cashback" OR "discount" OR "rebate" OR "percent earned/saved")
- 检查 memory 是否同时含: 百分比 (X%) + 美元金额 ($Y)
- 若都有: 注入 calculation hint "memory shows X% × $Y; product = $Z"
- 不强制 commit，只让 LLM 看到乘法已就位

风险: 极窄（"cashback" 词触发）。误伤面接近零。

### Tier 2 (中等风险，可考虑做)

**V8.2.3b: temporal loose-match hint（target: 9a707b82）**

- Trigger 模式: question 含模糊时间词 ("a couple of days ago", "a few days ago", "recently", "last week", "earlier this week")
- 检查 memory 是否含具体时间词 ("last weekend", "X days ago", "yesterday", specific date in past 7-14 days)
- 若有: 注入 hint "the following memory dates may match the question's vague timeframe: [list]"
- 仅 hint，不强制 commit

风险: 中等。"couple days ago"≈"last weekend"≈"earlier this week" 是软匹配，可能宽。但 hint-only（不强制）减小风险。

Codex 谨慎是对的：如果 hint 太宽，可能把 "last week" 误认 "couple days"。要严格定义触发模糊词集合（限 5-7 个明确模糊词）+ 匹配窗口 ≤ 14 天。

### Tier 3 (高风险，不推荐 V8.2.3 阶段做)

| qid | 为什么风险高 |
|---|---|
| d851d5ba 慈善 sum | 需要识别哪些 events 算"charity"，哪些不算。误算面大。|
| gpt4_d6585ce8 演唱会 order | 需要从多类事件中筛"concert" + 排序，定义"过去 2 个月"窗口，误选/漏选风险高。 |
| gpt4_ab202e7f 厨房物品 count | 需要 dedup 同一物品多次提及。RadioMind 已有 NumericAggregator 但已被 V8.2.1 用，没解决这题。|

### 不做（不在 deterministic 范围）

- gpt4_d12ceb0e 平均年龄: 数据可能根本不全
- d6233ab6 重逢建议: preference 层，需要 personalization 而非计算

## 决策建议

按 Codex 准则严格执行：

**做 V8.2.3a (cashback arithmetic helper)** 作为 Tier 1，理由：
- evidence 完整在 retrieve top-K
- 计算极简（rate × amount）
- trigger 模式极窄（"cashback"/"rebate"/"% earned" 等词）
- 几乎无误伤面

**暂不做 V8.2.3b (temporal loose-match)**，原因：
- 虽然在 Tier 2，但 Codex 已警示风险
- 它是 LLM behavioral hint 而非真计算，效果难以预测
- 如果 V8.2.3a 跑通了再考虑

**Tier 3 全部 hold**，等更稳定的 layer-by-layer 分析。

## 实施计划

V8.2.3a (cashback arithmetic helper)：
1. `src/radiomind/core/arithmetic_hint.py` — cashback rate detector + amount detector + multiplication hint
2. 单元测试：cashback / rebate / discount / non-arithmetic queries
3. Bench wire-in: run_longmemeval_mem0.py + run_locomo_mem0.py
4. Targeted smoke 仅跑 `9aaed6a3`
5. 通过后再决定全跑

## 文件

- 本 log: `projectBasicInfo/logs/2026-05-21-v823-fail-classification-cc.md`
- baseline: `bench/end_to_end/lme-s-v82-1-n100.json`
- 前序 log: `projectBasicInfo/logs/2026-05-21-v823-retrieval-premise-falsified-cc.md`
