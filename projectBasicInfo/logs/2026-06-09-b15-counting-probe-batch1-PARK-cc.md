# B-1.5 — counting 簇 read-only probe（第一批）→ PARK

> 作者: Claude Code (cc) ｜ 日期: 2026-06-09
> 范围: 只读 diagnose probe,分阶段。不改代码、不实现修复。
> 前置: B-1（counting 簇 NEEDS_PROBE）。结论: **第一批即定性,提前 PARK,不跑第二批。**

---

## 1. 第一批（3 代表 qid,FAIL artifact 程序化选自 current-main 3-run）
全部 FAIL 落在 run1(baseline),三种不同失败形态。`diagnose_qid --e2e-result`,read-only。

| qid | gold | layer | gold in top-30 / top-200 | answer 形态 |
|---|---|---|---|---|
| `9ee3ecd6` | 100 | helper_refusal* | **15/30**, 22/200, ranks 1-16 | concrete-wrong "300" |
| `gpt4_194be4b3` | own 4 | helper_refusal* | **19/30**, 52/200, ranks 12-21 | 截断 "You currently own" |
| `d3ab962e` | 8 miles | helper_refusal* | 1/30, 16/200, rank 6 | abstain |

\* `diagnosis.layer=helper_refusal reason="savings refused: no_trigger_match"` 是**噪声标签**:
savings helper 与这些题无关,只是 refused[0] 偏置（DEV_WORKFLOW §4 已警示 layer 由 refusal 驱动,
深读需看 retrieval+answer）。所有 counting helper（savings/cashback/person_age/age_interval）
对三题全 `no_trigger_match`/`skill_did_not_fire` —— **这些题无专用 helper,通用路径也没钉死答案**。

## 2. 判读: 不是可修检索簇,是 answer-path

**核心**: gold evidence 充分进窗（9ee3ecd6 15/30, gpt4_194be4b3 19/30）,answer 仍错 →
**不是 `proof_input_turn_missing` / `retrieval_gap`**（evidence 明明在 top-30）,而是
**answer-LLM 把检索到的数据用错**:
- 9ee3ecd6: 证据在(rank 1-16),却选错数（答 300 而非 100,remaining vs total tier 混淆）。
- gpt4_194be4b3: 证据在(19 条),却生成截断（verbose thinking 吃 token,strip 留残桩）。
- d3ab962e: top-30 仅 1 条(top-200 有 16),over-abstain。这条**唯一带一点检索稀疏**,但
  top-200 evidence 充足,且 answer 是 abstain 而非检索空。

→ 三者机制收敛到 **answer-generation（concrete-wrong / truncation / over-abstain）**,
正是 VR-2c 证明的主方差源、VR-4b 证明 self-consistency 不可修的那一类。**不是共享的、
可窄修的 retrieval/aggregator 缺失机制。**

## 3. 决策（按 B-1.5 预设规则）
预设: "主要是 concrete_wrong / answer-path stochastic → counting 簇不是可修检索簇,提前 PARK。"
→ 命中。**counting 簇 PARK。不跑第二批**（gpt4_f2262a51/c18a7dc8/b46e15ed）——第一批已覆盖
counting 三形态（选错数/截断/abstain）且全指向 answer-path;c18a7dc8 本就是已知
concrete_wrong_bypassed_committer,不会翻案。

## 4. 这对 SOTA 目标意味着什么
- counting 簇（最大同机制簇,14 个）的不稳 **不在检索/聚合,在 answer-LLM 对已检索数据的
  使用**。这与整条 VR 线一致: 主噪声是 answer generation,且不可靠靠加 helper/检索修。
- **没有 OPEN B-2 的窄可修簇。** B-1 五簇全部归宿:
  - counting → PARK（answer-path,本 log）
  - subjective preference → PARK（gold-ceiling）
  - ordering / open-vocab cardinality → PARK（单题/§5）
  - single-session recall → PARK（无同机制）
- → **架构提升线（B）当前无 read-only 证据支持的可修立项。** current-main 0.91 中心是
  answer-model 能力 + 噪声的真实反映;要过 0.92 的剩余路径**不是 RadioMind 记忆侧的窄修**,
  而是 answer-LLM 侧（更强/更稳的 answer 模型,或 answer prompt 约束数值表述——后者是
  prompt 工程,需独立验证且不属"架构记忆提升"）。

## 5. 唯一可能的非 PARK 余地（留给未来,不在此开）
若要在记忆侧帮 answer-LLM 把数值用对,可设想"通用数值证据高亮"——把检索到的关键数值
turn 在 prompt 里结构化前置(类似已有 atomic_section,但通用化)。但:(a) VR-2c 证明固定 store
下 answer 仍摇摆,高亮未必稳;(b) 已有 6 个专用 helper 走这条路仍不稳,通用化风险更大
（blast-radius 宽,违反"不全局大改"）;(c) 需新证据证明它能稳定 ≥2 qid。**故不 OPEN,
记为潜在方向,需专门实验立项。**

## 6. 不做 / 守住
不改代码、不跑第二批、不跑 n=100、不开 helper、不改 README、不实现修复。

## 7. 结论
**B（架构提升线）当前 PARK。** B-1/B-1.5 read-only 审计未找到可窄修的同机制检索/聚合簇;
最大簇 counting 的真因是 answer-generation（已证不可靠修）。current-main 诚实中心 0.91 维持,
对外口径已诚实（VR-final）。重开 B 需: 一个**新的、有 ≥2 同机制证据**的可修方向（如通用数值
高亮实验证明有效）,或 answer 侧能力/约束变化。
