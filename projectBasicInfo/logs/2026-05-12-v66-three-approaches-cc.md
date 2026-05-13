# 2026-05-12 V6.6 题干理解三方向探索 — atom/embedding 替代 LLM 题干 trinity

## 背景

V6.5 系列（V6.5/V6.5.1/V6.5.2/V6.5.3/V6.5.4）5 次独立 LoCoMo 10-qid smoke 实测**全部 5/10 PASS**——表面持平 V6.3 baseline，但内部翻牌（救一题倒一题）。根因诊断：

- V6.5 把 trinity 用在**题干侧（question-only 输入）做 simple/complex 二元 meta-judgment**
- LLM 在此任务上**跨次跑不稳定**（trinity classifier 测试 50%、4/10 题 retry-consistency cross-call inconsistent）
- 无论 wrap 多少层（agent 侧写 / applic gate / regex prefilter），底层 LLM 元判定噪声是结构性的

V6.5 系列已经触底。新视角：**RadioMind 已有 deterministic 的 atom decompose + embedding 机制**，能否绕开 LLM 题干判别？

## 三个候选方向

### 路径 1：query 自己原子化（结构化语法分析）

把 query 拆成结构化 atoms，从句法/语义结构推 form/granularity。

```
"What is X's favorite series about?"
  ├─ question_word: what
  ├─ possessor: X
  ├─ possessed: series
  ├─ preference_marker: favorite
  └─ introspection_marker: about  ← 关键
→ form = "topic", granularity = "concept"

"When did Gina get her tattoo?"
  ├─ question_word: when
  ├─ subject: Gina
  └─ predicate: got
→ form = "date", granularity = "specific_entity"
```

**实现**：`decompose_query_structure(query) → QueryAtoms`，用 regex/NLP 抽结构槽位 + 规则映射。

- **优点**：零 LLM cost，deterministic
- **缺点**：受规则覆盖度限制（未覆盖句式漏判）
- **复用现有架构**：新增（独立模块）

### 路径 2：memory atom 类型分布反推 query 形态

利用 atom decompose 的副产品——retrieved memories 拆出的 atoms 的**类型分布**反向暗示 query 期望什么 form：

```
Query: "What is Nate's favorite series about?"
Retrieved memories → decompose →
  atom: (Nate, has_favorite, series_X)
  atom: (series_X, has_genre, "fantasy")     ← abstract attribute
  atom: (series_X, contains_theme, "dragons")← abstract attribute
Dominant type = abstract_attribute → form = "topic"

Query: "When did Gina get her tattoo?"
Retrieved memories →
  atom: (Gina, got, tattoo, date=2023-02-08) ← temporal_event
Dominant type = temporal_event → form = "date"
```

**实现**：在 retrieved memories 已有 atom decompose 输出基础上加 atom type 投票函数。

- **优点**：零额外 LLM cost，deterministic，复用现有 atom decompose
- **缺点**：受 retrieve 质量限制；要求 atoms 有 type 字段
- **复用现有架构**：✓ atom decompose 已存在

### 路径 3：历史 query embedding KNN（数据驱动）

构建 query → (form, granularity) 标注库，新 query 用 embedding 做 KNN，找历史相似 query 投票。

```
新 Query: "What is Nate's favorite series about?"
向量化 → KNN top-5：
  "What is X's favorite Y about?"  → form=topic (history 80% PASS)
  "What does X think about Y?"     → form=topic (75%)
  "Y's main theme is what?"        → form=topic (90%)
→ 投票：form=topic 共识强
```

- **优点**：完全 deterministic，随数据增长越来越准
- **缺点**：需要 bootstrap 标注库（冷启动问题）
- **复用现有架构**：✓ embedding 已存在

## 三方向对比表

| 路径 | 实现复杂度 | LLM cost | 稳定性 | 泛化性 | 复用架构 |
|---|---|---|---|---|---|
| 1 query 原子化 | 中（语法规则） | 0 | 高（regex deterministic） | 受规则覆盖度限制 | 新增 |
| 2 memory atom 类型反推 | 低 | 0（atom 已有） | 高 | 受 retrieve 质量限制 | ✓ atom decompose |
| 3 历史 query KNN | 中（需冷启动） | 0 | 高 | 受标注库覆盖度限制 | ✓ embedding |

## 测试计划

按用户指示：
1. **先实施路径 2**（复用现有 atom decompose 架构 + 风险最低）
2. **跑 LoCoMo 10-qid flip smoke**（V6.5 系列同基准）
3. **再实施路径 1**（结构化语法分析）
4. **跑同 smoke**
5. **整理对比结果** + 决定是否合并

判定基线（V6.5 系列实测 5 次都 5/10）：
- ≥7/10 = 突破，进 LoCoMo n=100 完整验证
- 5-6/10 = 同 V6.5 持平，方向受限
- <5/10 = 退步，不可取

## 设计原则（避坑 V6.5 系列）

1. **不依赖 LLM 元判定**——V6.5 系列噪声根因，必须避开
2. **同 LLM 不能既生产又消费**（V6.4-B self-pollution 教训）
3. **保留 V6.5.4 框架**：agent_role / regex prefilter / applicability gate 都保留作为安全网；新机制只是**主决策方式**变化
4. **小+大累加，不替换**（V6.4-A 教训）：新方法输出的 directive 与 V6.3 answer 路径并存

## Next

- 实施路径 2 → smoke → 写结果
- 实施路径 1 → smoke → 写结果
- 对比 + 决策
- 更新此 log outcome 部分

---

## Outcome（2026-05-13 更新）

### 实施 + smoke 实测

按计划顺序实施 5 个变种，每个跑 LoCoMo 10-qid flip smoke：

| 变种 | 实现 | 10-qid PASS |
|---|---|---:|
| V6.6 path 2 | retrieved memory 内容 regex 信号分布（temporal/numeric/abstract_noun/proper_noun/judgment） | **6/10** ★ 单跑最高 |
| V6.6 path 1 | query 句法结构 regex（when_question/how_many/which_entity/introspection_about 等 11 条规则） | 5/10 |
| V6.6 sequential combined | path 2 → path 1 → V6.5 trinity 顺序 fallback | 4/10 |
| V6.6 multi-view (V6.6.2) | path 1 + path 2 + regex prefilter 并行三视角，渲染为多视角 prompt | 5/10 |

### 关键发现 1：V6.6.p2 单跑救回 V6.5 系列救不动的 c3 Joanna while writing

LoCoMo c3_94f06e1a00 "What does Joanna do while she writes?" gold = "stuffed animal Tilly"。

- V6.3 PASS（无 directive，LLM 直接 retrieve 找到 Tilly）
- V6.5 / V6.5.1 / V6.5.3 / V6.5.4 / V6.6.p1 全 FAIL（V6.5 系列 directive 推 LLM 列举活动 list，漏 Tilly）
- **V6.6.p2 PASS**：memory 中 "Tilly" 触发 proper_noun_entity 主导信号，directive 引导 LLM 关注具体物品

这是 V6.6.p2 的最大单点突破——之前 5 次独立跑无一版本救住这题。

### 关键发现 2：multi-view（V6.6.2）反而退步

multi-view 给 LLM 看 3 视角分析 + consensus/divergence 提示，理论上 ≥ max(p1, p2) = 6。但实测 5/10。退步原因推测：

- multi-view prompt 更长（3 视角描述）→ LLM 注意力被分散
- 三视角偶尔 form 字段 diverge → "weigh independently" 让 LLM 又开始 LLM 元判定（V6.5 不稳定的同款问题）

### 关键发现 3：所有版本 4-6/10 都在 LLM 噪声范围内

V6.3 + V6.5 series 4 个版本 + V6.6 4 个变种 = **11 次独立跑全部落在 4-6/10**。

`c1 Gina tattoo` 在 11 个版本中 PASS/FAIL 翻 5 次牌，同样 query 同样 directive，每次 retrieved memories 微差 → LLM 答案微差 → 边界 case 跨次不同。

**10 题样本 LLM 跑测噪声 ±1-2 道是常态**——任何 directive 方案的真实增益都被噪声盖过。

### 与 V6.5 系列对比

| 系列 | 思路 | 10-qid PASS | 稳定性 |
|---|---|---:|---|
| V6.5 (5 个变种) | LLM 题干 trinity 元判定 | 全 5/10 | LLM 元判定不稳，跨次 inconsistent |
| **V6.6 (4 个变种)** | **deterministic regex/signal** | **4-6/10** | regex/信号 deterministic，但 retrieved memories 跨次不同→输出微差 |

V6.6 比 V6.5 进了一步：**输出 deterministic**（同输入同输出），但答题侧 LLM 噪声仍然主导。

### 三方向最终评价

| 路径 | 实证表现 | 价值 |
|---|---|---|
| 路径 1（query 结构原子化） | 5/10 单跑 | 句法清晰题救回，但漏抽象/概念信号 |
| **路径 2（memory atom 信号反推）** | **6/10 单跑** | ★ 唯一单跑超过 V6.3 baseline 5/10；救回 Tilly 类题 |
| 路径 3（历史 query KNN） | 未实施 | 需要 bootstrap 标注库；现在数据规模不够 |
| 顺序合并 | 4/10 | LLM 噪声盖过结构信号 |
| 并行 multi-view | 5/10 | 三视角合并未带增益 |

### 结论

10 题样本在 LLM 答题噪声地带，**无法分辨 ±1 道的真实增益**。所有 V6.6 变种总分都在 4-6/10 区间。

V6.6.p2 单跑 6/10 是最佳，且**机制最简**（5 个 regex 信号 + 投票），但**未复测**——单点+1 道很可能是 LLM 跑测噪声偶然。

要看 V6.6 路径真实增益，必须升 LoCoMo n=100 大样本（噪声 ±2-3 道，相对增益 +5 道才 visible）。

### Open decisions

- **不合并 V6.6 到 main**：10 题增益证据不足
- **可选**：跑 V6.6.p2 LoCoMo n=100（~3-5h），如果 ≥ 0.92 → 合并；如果 ≤ 0.90 → 放弃 V6.6 路径
- **更深方向**：转方向 A（抽象层 ingest），把 form/granularity 信号在 ingest 时离线抽好，query 时只读不重推断——避开 LLM 答题侧噪声

### Lessons learned (added to methodology mental model)

1. **小样本 + LLM 答题噪声 = 增益盲区**：10 题在 LLM 噪声地带（±1-2 道），单点改进无法被验证。除非验证用 n≥50 样本。
2. **deterministic 信号 ≠ deterministic 输出**：V6.6 path 函数本身 deterministic，但 retrieved_memories 在 bench 跨次跑里因 ingest LLM 噪声不同 → path 输出微差 → 端到端结果跨次不同。
3. **multi-view directive 不是 silver bullet**：让 LLM 看更多 hint 反而分散注意力。诚如 V6.5.3 教训 ("简单+复杂 LLM 元判定不稳定")，在 LLM 上叠多视角不必然提升。
4. **答题侧 LLM 噪声是 V6 系列真正天花板**：题干理解层做对了，但答题侧 LLM 仍可能在同样 directive 下输出不同 — 这是 LLM 推理本身的不确定性，非架构能解。
5. **方向 A (ingest-time abstract layer) 是绕开 LLM 答题噪声的唯一架构层手段**：把 form/granularity 信号从 query-time 移到 ingest-time，query-time 只读，LLM 不再重新推断。

### Final state

- v6.6-memory-signals 分支保留 origin（包含 path 1 / path 2 / sequential / multi-view 实现 + 所有测试）
- main 仍是 V6.3（commit 571f52a）
- V6.5 系列分支保留作历史（v6.5-question-intent-trinity）
- 11 次独立跑数据保存在 bench/end_to_end/validation/v6.5*+v6.6*.json

