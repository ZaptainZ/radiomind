# B-1 — 架构提升 cohort 审计（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-09
> 目标: 从 unstable qids 找 ≥2 同机制、可窄修、非作弊的架构提升簇,把中心从 0.91 推过 0.92。
> 范围: 只读分类 + cluster 表 + OPEN/PARK/NEEDS_PROBE 决策。不改代码、不跑 n=100、不实现修复。
> 前置: VR 全线（中心 0.91±0.01;answer-gen 主方差;0.93 是 lucky 上沿）。

---

## 1. 输入（三层）
- **VR-4a 9 unstable**（current-main 真相集,3-run pass∈{1/3,2/3}）。
- **VR-3c 29 historical unstable**（候选池,cross-version,不当 current fail）。
- **current 3 个真结构地板**（cross VR-2c/3c/4a 确认）。

## 2. 最强信号: counting/aggregation 簇
**VR-3c 29 unstable 里 14 个是 counting/aggregation**（"how many / how much / total /
average"）;VR-4a 9 unstable 里 5 个同类。远超 ≥2 门槛,是唯一的大同机制簇。

14 个: c18a7dc8(年龄差) bb7c3b45(省了多少) 9ee3ecd6(还需积分) d851d5ba(募捐总额)
b46e15ed(过了几月) 9aaed6a3(返现) gpt4_194be4b3(乐器数) 031748ae_abs(带几个工程师)
gpt4_d12ceb0e(平均年龄) d3ab962e(徒步总距离) gpt4_8279ba02(几天前) 71017276(几周前)
gpt4_f2262a51(看了几个医生) 6aeb4375(试过几家韩餐)。

### 关键鉴别（决定 fixability,推翻"加新 helper"的直觉）
- **6/14 已有专用 helper**（9aaed6a3 cashback / bb7c3b45 savings / c18a7dc8 age-interval /
  gpt4_d12ceb0e person-age / d851d5ba charity-sum / 031748ae role）—— V8.x 各做过一个
  单题 helper,**仍 unstable**。
- **印证既有教训**（memory `project_lme_s_fail_families`）: per-qid helper 堆分无效,
  age committer 38% vs person_age hint 85%,**杠杆是 proof 输入的检索可靠性,不是 commit-closure**。
- helper_hints 在 v6.1.1 那跑对这 14 个**全 NONE** → helper trigger 本身脆弱（触发率低）。
- → counting 簇的不稳 **不是"缺 helper"**,而可能在更上游: (a) evidence turn 没进 retrieve
  top-k;(b) NumericAggregator 抽取/dedup 不稳;(c) answer-LLM 对同一检索的数值表述不稳
  （VR-2c 已证 9ee3ecd6 固定 store 仍 4 种答案）。三者 fixability 天差地别,**读 artifact
  无法区分,必须少量 diagnose**。

## 3. cluster 决策表

| cluster | qids (代表) | layer (待证) | fixability | risk | decision |
|---|---|---|---|---|---|
| **counting/aggregation** | 14 个（c18a7dc8, 9ee3ecd6, gpt4_194be4b3, gpt4_f2262a51, d3ab962e, d851d5ba, 9aaed6a3, bb7c3b45, gpt4_d12ceb0e, b46e15ed, 031748ae_abs, gpt4_8279ba02, 71017276, 6aeb4375） | 未定: retrieval-gap / aggregator-instability / answer-表述不稳 三选一,可能混合 | 高(若是 aggregator/检索) / 低(若是 answer-gen 噪声) | 中-高(NumericAggregator 是核心路径,改动 blast-radius 大) | **NEEDS_PROBE** |
| subjective preference | 1c0ddc50, b6025781, 09d032c9, afdc33df, 95228167, d6233ab6 (+others) | gold-ceiling（开放主观,judge 对 paraphrase 容忍但 gold 是 rubric） | 不可修(非作弊下) | — | **PARK**（结构地板,§5 已记） |
| temporal-ordering | gpt4_d6585ce8 | ordering 精度 | 单题,§5 已 PARK（OrderedEventList 1h 停） | — | **PARK** |
| open-vocab cardinality | gpt4_ab202e7f ("5 items" 列举) | open-vocab semantic extraction | 单题(此簇仅 1,不够 cohort) | — | **PARK**（除非并入 counting probe） |
| single-session recall | 778164c6, 1b9b7252, e66b632c 等 | retrieval recall 抖动 | 各异,无同机制 | — | **PARK**（单题摇摆,非簇） |

## 4. 结论: **counting 簇 = NEEDS_PROBE（唯一值得推进的）**
- counting/aggregation 是唯一 ≥2（实为 14）的同机制簇,**值得开**,但**不满足"直接进 B-2 实现"
  的门槛**——因为 fixability 取决于未定的 failure layer,且 6 个已有 helper 仍不稳证明"加 helper"
  方向已被证伪。
- **正确下一步 = B-1.5 窄 probe**（不是 B-2 实现）: 对 counting 簇里 4-6 个代表 qid 跑
  `diagnose_qid --e2e-result`(已有工具,read-only),用 path_summary.diagnosis.layer 区分:
  - `proof_input_turn_missing` / `retrieval_gap` → 检索可靠性是真因 → 可能有窄修（提升 counting
    evidence 的检索召回/排序,**全簇共享**,符合"≥2 同机制 + 窄面"）。
  - `concrete_wrong_bypassed_committer` / answer-表述不稳 → 是 answer-gen 噪声 → **PARK**
    （VR-2c/4b 已证不可靠且 self-consistency 无效）。
  - helper trigger 脆弱 → 修 trigger 召回（窄,但需确认 ≥2 同形）。
- 其余簇全 **PARK**: subjective preference（gold-ceiling）、ordering、open-vocab cardinality（单题）、
  single-session recall（无同机制）。

## 5. 门槛对照（counting 簇为何 NEEDS_PROBE 而非 OPEN B-2）
| 门槛 | 状态 |
|---|---|
| ≥2 qids 同机制 | ✅ 14 个 |
| gold evidence 可稳定取得 | ⚠️ 未证（probe 才知 evidence 是否进 top-k） |
| answer 可 deterministic derive | ⚠️ 部分（已有 6 helper 证明 derive 逻辑存在,但触发/检索不稳） |
| 修复面窄 | ⚠️ 取决于 layer（检索召回=窄;NumericAggregator 重写=宽,违反"不全局排序大改"） |
| 不 subjective | ✅ counting 客观 |
| 不 hardcode | ✅ |
| target-pack required 不受伤 | ⚠️ 6 个已是 required,改动须回归验证 |
→ 4 个 ⚠️ 必须靠 probe 消解,故 **NEEDS_PROBE**,不直接 OPEN B-2。

## 6. 不做（守住）
不改代码 / 不跑 n=100 / 不做 self-consistency / 不开 helper / 不改 README /
不把 historical unstable 当 current fail（VR-3c 29 个已标 cross-version,仅候选池）。

## 7. 下一步建议
- **B-1.5（read-only probe, 待授权）**: 对 counting 簇 4-6 代表 qid（建议 9ee3ecd6 /
  gpt4_194be4b3 / gpt4_f2262a51 / d3ab962e / c18a7dc8 / b46e15ed）跑 diagnose_qid
  --e2e-result,读 layer,判定真因是 retrieval-reliability（→ 可能 OPEN B-2 窄修）还是
  answer-gen 噪声（→ PARK）。仍 read-only,不实现修复。
- 仅当 B-1.5 证明 ≥2 qid 是同一 retrieval/aggregator 机制且窄可修,才 OPEN B-2。
