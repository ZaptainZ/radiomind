# 0.910 delta audit — 4 regressions vs V6.1.1（只读，不修）

> **⚠ SUPERSEDED（2026-06-05 同日）**: 本 log 的结论是 "PARK"。但 SOTA 是产品化前提
> （`01_PROJECT_OVERVIEW.md` 北极星），−2pt **不允许 park，必须 attribution**。后续以
> `2026-06-05-v611-restore-delta-attribution-cc.md`（V611-Restore 工作线）取代本结论：
> 先做 code-path diff audit（已证 runner answer-path 对这 4 qid 与 V6.1.1 等价），再做
> targeted repeat ×5 分离 stochastic vs regression。本 log 的逐题机制对照仍有效，仅
> "PARK" 决定作废。

> 作者: Claude Code (cc) ｜ 日期: 2026-06-05
> 类型: **只读 audit**。不改代码、不跑新 benchmark、不开 helper。
> 目的: 判断 current-main 0.910 vs 同题集 V6.1.1 0.930 的 4 个 regression 是否同一机制，
> 决定修还是 park。

---

## 1. 背景
`2026-06-04-lme-s-n100-current-main-baseline`: current-main LME-S n=100 = 0.910
（clean, judge_errors=0），**同一 100 qid 同顺序** vs V6.1.1 0.930，逐题对照
FIX 2 / REGRESS 4 / BOTH FAIL 5 = 净 −2。本 audit 只看 4 个 REGRESS。

数据来源（read-only，未跑 ingest）: 两个 artifact 的 per_query
（answer 文本 / gold / helper_hints / correct）。**范围边界**: "evidence 是否在
top-k" 需要重跑 diagnose ingest（= 新 run，禁止），故未做；以 answer 文本 +
helper_hints 触发 + 失败签名推断机制。

## 2. 逐题对照

| qid | qtype | gold | V6.1.1 answer (过) | current answer (错) | 机制 |
|---|---|---|---|---|---|
| `9ee3ecd6` | multi-session | 100 | "earn **100** more points" | "total of **300** points" | 数值选择：remaining(100) vs total(300)。无 helper。 |
| `gpt4_194be4b3` | multi-session | own 4 (列表) | "own **4** instruments: …" 完整列举 | **"You currently own"**（句子截断，无数字无列表） | answer 生成截断 / 空续写 artifact。无 helper。 |
| `d3ab962e` | multi-session | 8 miles | "is **8 miles**" | **"The information provided is not enough."**（pure abstain） | 多跳数值聚合上过度 abstain。current 有 answer_pure_abstain。 |
| `1c0ddc50` | single-session-preference | 避开 true-crime/self-improvement，要 history 等新类型 | 推荐深挖 history 播客 (Hardcore History/Lore) + Headspace | **反向推荐** "explore more podcasts in true crime, self-improvement" —— 正是 gold 说不要的 | 主观偏好对齐。DEV_WORKFLOW §5 已 park 的结构地板。 |

## 3. 机制判定

**4 个机制互不相同，无 ≥2 同形窄机制**:
1. `9ee3ecd6` — 数值"答案是哪个数"的选择（remaining vs total tier）
2. `gpt4_194be4b3` — answer 文本截断（生成 artifact，非逻辑）
3. `d3ab962e` — 聚合题过度 abstain
4. `1c0ddc50` — 主观偏好（parked 结构地板）

**且至少 2 个带 stochastic answer-path 签名**:
- `gpt4_194be4b3` 的 "You currently own" 截断 = 典型生成中断 / 空续写，re-run 极可能翻回。
- `d3ab962e` 的 pure abstain vs 之前给出 8 miles = answer-path 过度保守的抖动签名。
- `9ee3ecd6` 是 borderline 数值挑选，也易随采样翻动。

**关键 caveat（采样方差 vs 代码漂移）**: 两次 run 用**同一 deepseek-v3.2 answer 模型
但未 pin sampling**。4 个 borderline flip（含 1 截断 + 1 abstain）与 answer-LLM 采样
方差完全一致，**不能断定是代码/架构 regression**。要区分 code-drift vs sampling-noise，
需 3× 重复跑取众数——那是单独的、更大的任务（需另行授权），**不在本 read-only audit 内，
更不是开 fix**。

## 4. 修复门槛对照（均未满足）

| 门槛 | 满足? |
|---|---|
| ≥2 个 regression 同一机制 | ❌ 4 个各不相同 |
| gold evidence 可稳定抽取 | 部分（gpt4_194be4b3/9ee3ecd6 列表/数值可抽；1c0ddc50 主观不可） |
| 修复面窄 | ❌ 无共同机制可窄修 |
| 不影响 target-pack required | n/a（未到修复阶段） |
| 不需全局排序大改 | n/a |

## 5. 结论 — **PARK**

- 接受 current-main **0.910** 为内部 clean baseline。
- **不开 fix**：4 个 regression 无同形窄机制；≥2 个是 stochastic answer-path 签名；
  未 pin sampling 时 −2pt 无法证明是代码 regression 而非采样噪声。
- README **不更新** current-main claim（0.910 < 历史 0.930，且 delta 真伪未定）。
- 4 个 qid 的归属：`1c0ddc50` → 既有 parked subjective-preference 结构地板；
  其余 3 个 → "stochastic answer-path / 未 pin sampling 噪声候选"，不单独 park 成新方向。

## 6. 仅在以下出现时才重开（不主动追）
- 若将来做 **3× repeat n=100**（取众数）后这 4 个里仍有 ≥2 个稳定 wrong 且同机制 → 才进
  fix 评估（按 DEV_WORKFLOW §3 闭包边界）。
- 单次 run 的 borderline flip 不构成 reopen 证据。

## 7. 收尾
- 本 audit 纯只读：无代码 diff、无新 benchmark、无 helper。
- baseline sandbox `/tmp/rm-sandbox-lme-s-n100-refresh` 已清理（artifact 已入库，留存价值低）。
