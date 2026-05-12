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

（outcome section will be filled after both paths tested）
