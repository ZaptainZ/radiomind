# 2026-04-30 失败模式分类与解决思路

## 背景

n=100 v3 实测 0.860 后定位出 14 道失败 + 2 道 stress regression（合计 16
个失败点）。乍看每道是独特问题（B3 anchor、age_interval、charity dedup、
abstain 校准、errata...），但实际上**它们是 5 个深层问题各自暴露的不同
症状**。把它们按表面 qtype 分类只会让我们继续做 prompt 表面修补；按**根
因机制**分类才能产出可执行修复。

## 16 个失败点原始清单

| 来源 | qid | qtype | 表面问题 |
|---|---|---|---|
| n=100 v3 | 031748ae_abs | knowledge-update | 应 abstain 没 abstain |
| n=100 v3 | d851d5ba | multi-session | charity 总额 $2,750 vs $3,750 |
| n=100 v3 | c18a7dc8 | multi-session | age delta 0 vs 7 |
| n=100 v3 | d3ab962e | multi-session | hike sum 45 vs 8 |
| n=100 v3 | gpt4_ab202e7f | multi-session | 物品数 4 vs 5 |
| n=100 v3 | bb7c3b45 | multi-session | $300 误 abstain |
| n=100 v3 | d6233ab6 | preference | B3 anchor 没触发 |
| n=100 v3 | 95228167 | preference | B3 anchor 没触发 |
| n=100 v3 | 29f2956b_abs | single-session-user | 应 abstain 没 abstain |
| n=100 v3 | b46e15ed | temporal | 信息够却 abstain |
| n=100 v3 | 6e984301 | temporal | event_interval 算 9 wk 应 3 wk |
| n=100 v3 | gpt4_fa19884d | temporal | 非时间题被路由到 temporal |
| n=100 v3 | 370a8ff4 | temporal | dataset errata，主 bench 未过滤 |
| n=100 v3 | gpt4_59149c78 | temporal | "museum" 实体错配 |
| stress run 1 | gpt4_d12ceb0e | multi-session | parents ages "early 30s" inferable but abstained |
| stress run 2 | 59524333 | knowledge-update | gym time 选了旧记忆 |

## 五大根因分类

### Category 1: Abstain 校准双向错误（6 道）

**症状：**
- 应 abstain 没 abstain：031748ae_abs、29f2956b_abs（gold 明确说"info not enough"）
- 不该 abstain 却 abstain：bb7c3b45、b46e15ed、gpt4_fa19884d、gpt4_d12ceb0e

**根因：**
当前 prompt 用 `B4 PREMISE-VERIFICATION` 单一规则同时控制两个方向。规则
说"only abstain when memories actively contradict"——这条对**应 abstain
没 abstain**这一侧有效，但对"信息够却 abstain"这一侧没保护。模型在
range/inference 边界（"early 30s" 推算 parents 60+）选择保守。

**为什么 prompt 调参吃完红利：**
- 收紧 B4 → 救回 bb7c3b45，但放走 031748ae_abs
- 放松 B4 → 救回 031748ae_abs，但 bb7c3b45 又错
- 两个方向 zero-sum，prompt 表层修补无解

**真正的 fix：** 双 pass 显式分离

```
Pass 1 (生成答案): 像现在一样答
Pass 2 (abstain 决策门): 喂入 question + memories + draft answer
  → 输出严格的 yes/no abstain decision
  → 调用方采用决定
```

代价：每题多一次 LLM 调用（+~30% 答题成本）。
收益：6 / 14 失败属此类，理论上能从 0.860 → 0.92 左右。

**替代方案（不加 LLM 调用）：** 让 trinity 内部跑 abstain debate。守护者
（"信息不全就 abstain"）vs 探索者（"能推就答"）vs 精简者（"模糊就给
range"）。已经存在的基础设施，零额外成本。需要把 trinity 接入答题路径。

---

### Category 2: NumericAggregator 算法弱点（4 道）

**症状：**
- d851d5ba：charity bake sale 没归到 `charity_donations` 类
- c18a7dc8：age delta 直接输出 0
- d3ab962e：hike sum 45 mi 应 8 mi（多包含了不相关的 hike）
- gpt4_ab202e7f：物品数漏 1

**根因细分：**

(a) **Ingest 时 LLM 分类非确定性** (d851d5ba)：DashScope LLM 看到 "we
raised $1,000 for the local children's hospital (bake sale)" 时，class
判定有时是 `charity_donations`、有时是 `amount_events` 等通用类。
2026-04-27 加的 `class-aware dedup`（commit `836c78e`）让 LLM 和 regex
两条路并存以避免互相抹掉，但**这只解决了"merge 时谁覆盖谁"**，并不能解决
"LLM 这次干脆没识别成 charity"。v3 seed 下 LLM 偶发改变了分类，regex
也没救回（regex 是基于动词 "raised" + currency 模式，bake sale 这一句
不一定触发）。

(b) **Scope filter 过松/过紧** (d3ab962e、gpt4_ab202e7f)：scope query
"hikes I did on two consecutive weekends" 没把"那些不连续的 hike"过滤掉，
NumericAggregator 把所有标 `hiking` 类的事件都加了进去。

(c) **Skill 内部算术错** (c18a7dc8)：age_interval skill 收到了 user_age=32
和 graduation_age=25，应该算 32 - 25 = 7，却输出了 0。这是 skill 实现
bug，不是数据问题。

**真正的 fix：**

(a) → **多源 + 投票**：LLM 抽取 + regex 抽取 + 历史 NER 抽取（如果有）
三路并行，对**同一事件**投票决定 entity_class。当前两路并存（dedup）但
不投票。投票胜出的版本进 cardinal cache。

(b) → **Scope 二阶过滤**：当前 scope filter 用关键词匹配（"hike"），需要
增加**约束语义**层（"consecutive weekends"、"in March"）。这要求 query
parser 把约束抽出来，scope filter 按约束筛而不是只按 entity class。

(c) → **Skill 单元测试**：每个 skill 应有 deterministic gold-input test
覆盖。c18a7dc8 这种应在 CI 而不是 n=100 才暴露。

收益：~4 / 14 失败属此类，理论能从 0.860 → ~0.89。代价：算法层重构，
非小工作。

---

### Category 3: 检索召回不足（2 道 + 隐藏更多）

**症状：**
- d6233ab6、95228167：B3 PREFERENCE-ANCHOR 规则没触发——其实是因为
  user-specific 上下文（"我用 Adobe Premiere"等）没被检索到 prompt context。

**根因：**
B3 是**条件触发**：只有 prompt 里包含 user 的 specific tool / surface /
constraint，B3 才有锚可锚。当前检索 top-k 不够多 / score 阈值不够低 /
preference_context_injector skill 召回不准时，user context 根本没进 prompt。
B3 规则形如虚设。

**这一类容易低估**：preference 类总共 16 题，2 道明显失败，但其他 14 道
PASS 的有多少是"靠 generic answer 蒙对"了？无法知道，但很可能有几道是
fragile pass。

**真正的 fix：**
- 召回 audit：对每道 preference 题打印 retrieved memories + B3 anchor
  trigger flag，统计真实触发率
- 如触发率 < 80%，说明召回是瓶颈，加大 top-k 或换 retrieval signal
  （preference query 用 contextual rerank 而不是默认 BM25+vector）
- 长期：preference qtype 单独走 dedicated retrieval pipeline（已有
  `preference_context_injector` skill 框架，需要加 logging + 强化）

收益：~2 + 几道隐藏 fragile pass，~3-5 道。

---

### Category 4: 实体跟踪 / 路由 (~2 道)

**症状：**
- gpt4_59149c78：haystack 里有多个 museum（MoMA、Met、City Art Museum），
  问题问"the museum where the Ancient Civilizations exhibit was held"，
  模型选了 City Art Museum 而非 Metropolitan
- gpt4_fa19884d：问题是关于音乐流派，被错误路由到 temporal skill 后
  abstain（其实根本不该走 temporal）

**根因：**
RadioMind 的 attention signature 是按 `wants` tag 路由（temporal、cardinality、
preference 等），但**没有显式的 entity disambiguation 阶段**。当 user
说 "the museum I went to" 时，需要先确定**哪个 museum 实体**，再去取
该实体的 attribute。当前架构是把所有 "museum" 关键字命中的 memory 都
放进 prompt，靠 LLM 自己挑——LLM 经常挑错。

类似地，gpt4_fa19884d 被路由到 temporal 是因为 question 里有"after I
moved"等时间触发词，但实际问的是音乐流派。**路由分类器 false positive**。

**真正的 fix：**
- 加 **entity-link 阶段**：query 进来后先用 NER 识别实体提及 + 候选
  实体集，再做 attribute 检索。这是 KG 风格的设计。
- **路由分类器的 confidence 阈值**：当前 attention 路由是硬路由（"问 X
  类型 → 走 X skill"）。改成 soft 路由（多个 skill 并行输出，最后由
  meta layer 投票）会更鲁棒，但成本高。

收益：~2 道。代价：架构层改动，相对不划算的方向（除非顺便能解决其他
问题）。

---

### Category 5: 基础设施 / determinism (~2 道)

**症状：**
- 370a8ff4：errata gold 错，主 bench 没有 errata filter
- d851d5ba：v2 fix 在 v3 seed 又破——同代码不同 seed 不同结果

**根因：**
- errata filter 只在 `regress_activated_channels.py`，没移植到主 bench
- d851d5ba 的 fix 依赖 LLM 的 ingest 行为，LLM 输出本身非 deterministic

**真正的 fix：**
- errata filter 5 行代码移植，1 道立即回血
- d851d5ba 类问题需要 deterministic regression test：固定 LLM 输出
  （vcr-style）+ 验证 dedup 行为，CI 跑

收益：1 道立即回 + d851d5ba 不再每次 seed 都炸。代价：低。**ROI 最高**。

---

## 修复优先级建议

| Pri | 类别 | 道数 | 工作量 | 预期收益 |
|---|---|---:|---|---|
| **P0** | Cat 5 errata filter 移植 | 1 | <1h | 0.860 → 0.870 |
| **P1** | Cat 1 trinity 接入 abstain | 6 | 2-3 天 | 0.870 → 0.92 |
| **P1** | Cat 5 d851d5ba deterministic test | 1 | 1 天 | 0.92 → 0.93 |
| **P2** | Cat 2 NumericAggregator 多源投票 + scope 二阶 | 3 | 1 周 | 0.93 → 0.95 |
| **P2** | Cat 2 skill 单测覆盖 | 1 | 2 天 | 同上 |
| **P3** | Cat 3 preference 召回 audit | 2-5 | 2 天 | 0.95 → 0.96 |
| **P4** | Cat 4 实体跟踪 / soft 路由 | 2 | 2 周 | 0.96 → 0.97 |

P0 + P1 是高 ROI 区，能从 0.860 到 0.92-0.93。P2 是真正的架构投资，把
0.93 推到 0.95+。P3-P4 ROI 递减。

## 关键洞察

1. **不要再单题 patch prompt**。表面 6 道 abstain 失败看似都是 B4 调参，
   实际上是**一个根因**（单 pass 决策不能同时管住两侧），需要架构层
   分离 (Pass 1 答 + Pass 2 abstain 决策门 / 或 trinity 内部 debate)。

2. **NumericAggregator 是 multi-session qtype 的瓶颈**，不是 prompt。
   v2 d851d5ba 修过 v3 又破说明当前修复**依赖 LLM 偶发对类**，根本
   解法是多源投票 + scope 二阶过滤 + skill 单测。

3. **B3 PREFERENCE-ANCHOR 看起来是 prompt 问题，实际可能是检索召回**。
   prompt 里没 user context，B3 再怎么写都没用。先 audit 召回率再决定
   修哪一层。

4. **抽象层级思考**：把 16 个失败映射到 5 个根因，再把 5 个根因按 ROI
   排序。这种"从症状到机制再到优先级"的思考方式，比"每周修 1-2 个失败
   qid"的搬砖式高效得多。

## 修改文件

- 本日志（详细分析）
- 后续 commit 会按 P0 → P1 顺序落地

## 不做什么

明确**不**做：
- 继续微调 B4 / B3 / RULE 12 等 prompt 表面规则（边际收益已耗尽）
- 单题 patch（治标不治本）
- 再做一次 stress test（同样的方法学不会带来新信息）

---

## 2026-05-02 修订：核心方法论对齐

之前的修复方案把 "trinity / attention / 多 LLM 调用 / 算法工程" 混为一谈。
现在锐化定义：

**核心方法论（仅两条）：**
1. **三体（trinity）**——三方辩论，可多轮讨论，可子三体递归（每个单体内部
   再展开三体）。"多轮次"是 trinity 内部的迭代深度，不是独立原语。
2. **注意力（4th law）**——`AttentionSignature` 驱动的层间 wants 分发。

**系统设计（工具层）：** skills、NumericAggregator、scope filter、
entity-link、retrieval pipeline、errata filter、deterministic test……
都是上面两个原语的具体实现载体，可替换、可重构。

### 16 个失败点重新对齐

| Cat | 失败点 | 对齐方式 |
|---|---|---|
| 1. Abstain 校准（6 道） | trinity（守护/探索/精简，多轮讨论；守护者内可再子三体讨论"信息算不算够"） |
| 2a. entity_class 抽取（1-2 道） | trinity（LLM/regex/NER 三方抽取，分歧时子三体深挖原文证据） |
| 2b. scope 过滤过松（1-2 道） | attention（query wants 二阶约束传到存储层） |
| 3. 检索召回（B3 anchor，2+ 道） | attention（preference qtype 显式声明 user_specific_anchor wants） |
| 4a. soft routing（1 道） | trinity（skills 多方并行 + 投票）+ attention（每 skill 声明 wants 域） |
| 4b. entity 消歧（1 道） | trinity（频率/上下文/attribute 三方，按 attribute 子三体） |
| 5a. errata filter（1 道） | 纯系统设计（不应硬套核心原语） |
| 5b. d851d5ba determinism | 由 Cat 2a 的 trinity 投票自然解决（不依赖单 LLM 输出） |
| skill bug c18a7dc8（1 道） | 纯系统设计（单元测试） |

**13 / 16 由 trinity + attention 覆盖，2 道是工程修复，1 道是 errata。**

### 实施次序

| Pri | 失败 | 落地 |
|---|---|---|
| **P0** | Cat 5a errata filter 移植 | 工程，<1h，立即 |
| **P1** | Cat 1 trinity 接入答题路径（abstain 决策） | 已存在 trinity，加 wire-up + abstain 三体定义 |
| **P1** | Cat 2a NumericAggregator entity_class trinity 投票 | 把单一 LLM 抽取改为 LLM/regex/NER 三体；分歧时子三体 |
| **P2** | Cat 2b/3 attention `wants` 二阶过滤 | retrieval 层接 wants tag，preference / scope 都受益 |
| **P2** | Cat 4 soft routing trinity | skills 多方 + attention domain 声明 |
| **P3** | Cat 5 工程修复（skill 单测、errata CI） | 防御层 |

### 设计原则

- **每个新失败点先问"这是 trinity 没辩够 / attention 没分发到 / 还是纯系统问题？"**
  前两个用核心原语，第三个用工程。
- **不让系统设计层假装自己是核心原语**——dedup、scope filter、retrieval
  调参就是系统设计，不是 trinity 也不是 attention。诚实定位。
- **trinity 和 attention 之间也不互替**——trinity 是决策机制，attention
  是分发机制；多数失败需要两者协同（先 attention 路由，trinity 再决策）。
