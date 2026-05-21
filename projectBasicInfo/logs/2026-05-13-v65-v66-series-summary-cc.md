# 2026-05-13 V6.5 + V6.6 系列总结 — 题干侧深度探索的天花板

## 背景

V5 baseline (LongMemEval-S 0.920) → V6.1.1 (LongMemEval-S 0.930 实测，等同 MemMachine SOTA) → V6.2 GAP-C 失败回滚 → V6.3 (LongMemEval 4-qid + LoCoMo n=100 = 0.900) 作为新 main baseline。

之后 V6.4 / V6.5 / V6.6 系列**专注 LoCoMo** 上"题干侧理解"的探索，目标突破 V6.3 LoCoMo 0.900。

历经 V6.4-A (entity-trinity 替换 wrap) → V6.4-A.1 (accumulate fix) → V6.4-B (character profile, self-pollution -6) → 全部回滚。

V6.5 系列引入"题干侧 trinity"思路：

```
V6.5    LLM trinity 拆题干 + 注入 directive
V6.5.1  + applicability gate（trinity 自评是否适用）
V6.5.2  + trinity.debate agent_role 参数化（"answerer" vs "question-intent-analyzer"）
V6.5.3  + 强化 question-intent-analyzer preamble（语言学家比喻 + 显式禁止 stance）
V6.5.4  + regex prefilter（simple/complex 0-cost 前置筛选）
```

V6.6 系列转 deterministic 思路（无 LLM 题干元判定）：

```
V6.6 path 1   query 句法结构 regex（11 条规则映射 form/granularity）
V6.6 path 2   retrieved memory 内容 regex 信号（5 种类型分布投票）
V6.6 seq      path 2 → path 1 → V6.5 trinity 顺序 fallback
V6.6.2 mv     path 1 + path 2 + regex 并行三视角合并
```

## 实测数据汇总（LoCoMo 10-qid flip set）

11 次独立跑：

| 版本 | 实现核心 | 10-qid PASS |
|---|---|---:|
| V6.3 (baseline) | 无 directive | 5/10 |
| V6.5 | LLM trinity simple/complex 二元判定 + directive | 5/10 |
| V6.5.1 | + applicability 自评 gate | 5/10 |
| V6.5.3 | + agent_role 框架 + 强化 preamble | 5/10 |
| V6.5.4 | + regex prefilter 前置过滤 | 5/10 |
| V6.6 path 1 | query 句法结构 regex | 5/10 |
| **V6.6 path 2** | **memory 信号分布 regex** | **6/10** ★ |
| V6.6 seq combined | path 2 → path 1 → trinity fallback | 4/10 |
| V6.6.2 multi-view | 三视角并行 | 5/10 |

**核心观察**：11 次跑都落在 4-6/10 区间。`c1 Gina tattoo` 在 11 个版本中 PASS/FAIL 翻 5 次牌——这是 **LLM 答题侧的端到端噪声**，10 题样本上 ±1-2 道是常态。

## V6.5 vs V6.6 思路对比

| 维度 | V6.5 系列 | V6.6 系列 |
|---|---|---|
| 题干判别机制 | LLM trinity 元判定 | regex / 信号 deterministic |
| LLM cost/query | 2-3 calls | 0 |
| 跨次稳定性 | 低（retry-consistency 4/10 题 inconsistent） | 高（规则 deterministic） |
| 10-qid 最佳 | 5/10 | 6/10 (path 2) |
| 实际增益 | 噪声盖过 | 噪声盖过 |

V6.6 比 V6.5 稳定性提升（无 LLM 元判定噪声），但**答题侧 LLM 噪声**让总分仍在 4-6/10 噪声地带。

## 哲学层洞察（更新到 CORE_METHODOLOGY 心智模型）

### 1. 题干 trinity 不适合 binary meta-judgment

V6.5/V6.6 实证：trinity 在结构化字段任务（granularity / form 多值枚举）上稳定，但在 `simple` vs `complex` 二元元判定上跨次跑结果完全相反（V6.5 系列 4/10 题 retry-consistency 失败）。LLM 在这类 meta-classification 上**没有稳定的 ground truth 锚定**。

> 推论：trinity 应用在"有锚点的多视角辩论"（answer trinity / anchor selection），不应用在"无锚点的元判定"（simple/complex / applicability 自评）。

### 2. agent 侧写应该是 trinity 一阶参数（V6.5.2 永久收益）

`trinity.debate()` 原本 V5 时 prompt 内嵌 "answerer" 角色。V6.5 在题干侧用同一 prompt → LLM 严格按"answer + abstain on thin evidence"执行 → 大量 abstain。

V6.5.2 引入 `agent_role` 参数 + `_AGENT_ROLES` library。这是**结构性改进**，未来所有 trinity 调用都可显式配置 agent 侧写。即使 V6.5 整体没合并，这个框架修复仍有价值。

### 3. multi-view directive 不必然提升

V6.6.2 把 3 视角（query 结构 + memory 信号 + lexical marker）合并喂给 LLM，理论上 ≥ max(单视角)。实测反而 5/10，比 path 2 单跑 6/10 退步。

> 推论：让 LLM 看更多 hint 不必然提升 — prompt 注意力被分散 + 视角 diverge 时 LLM 又开始 LLM 元判定（不稳）。

### 4. 答题侧 LLM 噪声是 V6 系列真正天花板

题干理解做对了（V6.6 path 2 `c3_a9fddfe69b` "What is X about?" 完美输出 form=topic granularity=concept），但 LLM 在 directive 引导下**仍可能答错**——这是 LLM 推理本身的不确定性，不是题干层架构能解。

证据：`c1 Gina tattoo` directive 在 11 个版本里 stably 是 `form=date`，但 PASS/FAIL 跨版本翻 5 次牌。

### 5. 方向 A（ingest-time abstract layer）是绕开 LLM 答题噪声的唯一架构手段

把 form/granularity 信号从 query-time 移到 ingest-time。query-time 只读不重新推断，避开 LLM 答题侧噪声。这是未实施的方向，理论上是真正能突破天花板的路径。

## 当前 git 状态

```
origin/main:              571f52a  V6.3 (LoCoMo 0.900 baseline)
origin/v6.5-question-intent-trinity:  V6.5 系列（5 个版本提交，未合并 main）
origin/v6.6-memory-signals:           V6.6 系列（4 个变种提交，未合并 main）
```

## Open decisions

- **不合并 V6.5 / V6.6 到 main**：10 题增益证据不足；噪声地带无法验证 ±1 道改进。
- **可选 (A)**：跑 V6.6 path 2 LoCoMo n=100（~3-5h）。如果 ≥ 0.92 → 合并 V6.6.p2；如果 ≤ 0.90 → 放弃 V6.6 路径。
- **可选 (B)**：直接转方向 A（ingest-time abstract tag），绕开 query-time 改进的天花板。
- **可选 (C)**：写完整 V6 系列 outcome 文档，停在当前合理点，转其他优先级（LongMemEval n=100 V6.3 / V6.5 没测过 — 看 V6.3 在 LongMemEval 上是否仍 0.930）。

## Lessons for future V7+

1. **小样本验证陷阱**：不要在 10 题集上反复迭代 — 10 题样本噪声地带宽 ±2，看不出 ±1 改进。验证最小样本 n=50。
2. **LLM 元判定不可信**：任何 "LLM 自评是否适用" 都是潜在不稳定源。
3. **架构层改进 > query-time 改进**：query-time directive 受 LLM 答题噪声限制；ingest-time 信号一次抽好持续受益。
4. **trinity 的边界**：trinity 适合多视角答题、anchor selection、entity disambiguation，不适合无锚点的元判定。
5. **methodology 心智模型已增加 5 条规则**（详见上文"哲学层洞察"）。
