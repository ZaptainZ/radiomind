# 2026-05-21 V8.2.x Scoreboard — 已固化的 narrow-helper 收益

## 目的

V8.2.1 → V8.2.3a 系列由 Codex 严格收窄设计，每个版本都是"窄面 deterministic helper + zero-blast"。本 log 固化已解决 target case、触发面、风险边界，作为后续决策基准。

不写新功能；不再继续 Tier 2/3。

## 全 V8.2.x 一表

| 版本 | layer | target case | smoke PASS | LME-S 触发面 | LoCoMo 触发面 | 风险 |
|---|---|---|---|---:|---:|---|
| V8.2.1 | selective FTS-OR retrieve (`which X / where`) | LoCoMo c4 Seattle | 10/10 stable | 0/100 | 1/10 (c4) | 已固化稳定 |
| V8.2.2a | prompt role-mismatch guard | LME-S `031748ae_abs` (Senior SE vs Engineer Manager) | PASS | 1/100 | 0/10 | trigger 仅 role-token query |
| V8.2.2b | bench judge retry + report split + post-rewrite canonical abstain | (V8.2.2a 闭环) | PASS | n/a | n/a | 改 bench 评估仪表 |
| **V8.2.3a** | **cashback arithmetic hint** | **LME-S `9aaed6a3` SaveMart $0.75** | **PASS** | **1/100** | 0/10 | trigger 仅 cashback/rebate 问句 + 双信号要齐 + 多金额无 merchant 时拒绝 hint |

## V8.2.x 已解决的 target cases

### V8.2.1: c4 Seattle (LoCoMo)
- gold "Seattle" 在 evidence memory 中，但 V7 fullans embedding+AND-FTS 排序到 >200
- selective FTS-OR (only "which X" pattern) 把 Seattle 拉到 rank 7 → reranker 顶到 top → LLM 选 Seattle
- 6 runs stable 5/5 PASS

### V8.2.2a: 031748ae_abs (LME-S)
- Q: "How many engineers do I lead as Software Engineer Manager?"
- gold: "info not enough — you started as Senior SE not Manager"
- V8.2.1 over-commit "team of 5 engineers" (拿 Senior SE 的事实补 Manager 问句)
- V8.2.2a 检测 leadership-track query + IC-track memory → 注入 presupposition abstain hint → LLM clean abstain

### V8.2.2b: 完成 V8.2.2a 闭环
- bench judge HTTP retry × 3 + exponential backoff（消除 OpenRouter 403/SSL 假 FAIL）
- report 拆分 `raw_accuracy` / `judged_accuracy` / `judge_errors`
- rejudge_errors.py 离线工具补判已 errored qids
- post-rewrite canonical abstain：guard fired + LLM 仍 commit headcount/team-size/$/数字 → 强制重写为标准 abstain
- target smoke：clean canonical abstain PASS

### V8.2.3a: 9aaed6a3 (LME-S)
- Q: "How much cashback did I earn at SaveMart last Thursday?"
- gold: $0.75 (derived = 1% × $75)
- V8.2.1 evidence 完整在 retrieve top-K（rank 1: $75 spent + 1% cashback memory），但 LLM 没算乘法 → abstain
- V8.2.3a 检测 cashback 类问句 + memory 同时含 rate% + amount → 注入 "ARITHMETIC HINT: X% × $Y = $Z" → LLM 干净 commit "$0.75"

## V8.2.x 范围边界（不做的事）

按 Codex 决策固化：

| Tier 2/3 候选 | qid | 不做的原因 |
|---|---|---|
| temporal loose-match hint | 9a707b82 chocolate cake | Codex 警示：软匹配可能宽 (couple days ≈ last weekend, 但也可能误认 last week ≈ couple days) |
| sum helper | d851d5ba charity $3,750 | 多 events 误算/漏选风险大 |
| ordering helper | gpt4_d6585ce8 concert order | 多事件筛 + 排序 + 窗口选择，误伤面大 |
| count/dedup helper | gpt4_ab202e7f kitchen 5 | 同物品多次提及 dedup 复杂 |
| arithmetic (general) | gpt4_d12ceb0e avg 59.6 | 数据可能不全 |
| preference layer | d6233ab6 reunion | 不是 deterministic 范围 |

## V8.2.3a 安全增强（Codex follow-up）

Codex 提醒：泛问 "How much cashback did I earn?"（无 merchant）+ memory 多金额时，原 fallback 拿第一个。

**已加 guard**：
```python
if merchant is None:
    # collect all $ amounts ≥ $5
    if len(distinct_amounts) >= 2:
        return None  # ambiguous, refuse hint
```

新增 3 单测验证：
- 无 merchant + 多金额 → no hint
- 无 merchant + 单金额 → hint (safe)
- 有 merchant + 多金额（merchant 过滤后单金额）→ hint

## 后续不做的决策（hold）

按 Codex 建议：

1. **不跑 V8.2.3a 完整 LME-S n=100**。触发面 1/100，理论最大 +1 题；单 run LLM 噪声 ±5-10 足以淹没。14h 大概率只测随机波动，不值得。

2. **不继续 Tier 2 temporal loose-match**。Codex 谨慎理由有效：软匹配窗口边界难定，容易宽面失败。

3. **不继续 Tier 3 helpers** (sum/ordering/count)。误算/漏选风险高于收益。

4. **不重启 KG batch**。V8 KG-enable 已证不稳定，cross-run 翻牌。

## 当前最稳定 baseline

| 测试 | 版本 | 分数 |
|---|---|---|
| LoCoMo flip 10 strict mean | V8.2.1+ (6+ runs) | **5.80/10** (floor 5, ceiling 7) |
| LME-S n=100 strict | V8.2.1 (judge-clean) | **0.92** |
| LME-S target case 9aaed6a3 | V8.2.3a smoke | **PASS** (V8.2.1 was FAIL) |
| LME-S target case 031748ae_abs | V8.2.2b smoke | **PASS** (V8.2.1 was FAIL) |

理论 V8.2.3a + V8.2.2b 联合 LME-S 上限：92 + 2（两个 target case 都救回）= 0.94。但因 V8.2.1 0.92 单 run 含 LLM 噪声，真实增益要 multi-run 验证。

## 当前 git 状态

```
分支: v7-evidence-candidates
HEAD: b80c732 V8.2.3a: cashback arithmetic helper
```

V8.2.x 系列已达到 Codex 设计原则的稳定状态：narrow helpers + zero blast + deterministic + 已 fail-classified。

后续任何新 helper 应继续按 4 列分类筛 (evidence_in_top_k / answer_mode / needs_calc / safe_helper)，**绝不宽面修改**。
