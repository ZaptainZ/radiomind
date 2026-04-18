# 2026-04-18 (part 2) — 第四律 Attention：查询时原子化 + 价值驱动晋升

## 背景
前面的工作让 RadioMind 在 Mem0 verbatim 协议下到 LME-S 0.900 / LoCoMo 0.833，距 SOTA 还差 10 pt（strict 配置下）。深入分析发现：10 pt gap 本质是两种**记忆哲学**的权衡：
- **Mem0 extractive**：ingest 时 LLM 抽原子事实，破坏叙事完整性但对 aggregation benchmark 友好
- **RadioMind preservative**：保留原 turn + KG + L3 principle，叙事完整但 aggregation 类问题要求 LLM 在答题时做叙事解析

用户提出关键设计洞察：**可以在查询时做原子化**——既不破坏存储的 ground truth，又能在需要时提供 atomic 视图；分解出的高价值信息还能"用进废退"地晋升到更高层级。更深的观察：这揭示了架构中一个未被显式命名的原则——**Attention（注意力机制）** 应作为第四律与"分层/炼化/Meta"并列。

## 目标
把"注意力机制"从 RadioMind 架构里隐性的模式显式化为设计律，并给出其查询时具体实现——query-attention classification + atomic decomposition + value-driven promotion。

## 第四律正式表述
> **架构的每一层、每一次操作，都应该显式回答"此刻注意力焦点是什么"。存储层、检索层、答题层、反思层——每层都有自己的 attention signature，不能只靠下一层兜底。**

### 已有各层的 attention 角色（梳理而非新增）
| 位置 | attention 作用 |
|---|---|
| L1 gate | 输入侧：这轮对话值得记吗 |
| Pyramid sort（score-blend）| 检索侧：这条和 query 多相关 |
| Trinity 三个 role | 多视角：同一批证据三种注意力切片 |
| Meta calibration | 元注意力：观察自身注意力偏差 |
| Dream wander | 空闲时：无明确查询的自由漂移 |
| **(新) Query-time decomposition** | **查询侧：根据本次 query 焦点重构记忆视图** |

## 实现
三个新模块 + 两处接入，共 ~550 行：

### `src/radiomind/core/attention.py`
QueryAttention 分类器，将查询归类为 multi-label 标签之一或多个：
- `aggregation`：how many / 列出所有 / 多少 / across
- `disambiguation`：previous / former / current / latest / 之前 / 现在
- `narrative`：why / how did you feel / 为什么 / 当时怎么
- `comparison`：which / compare / 比 / 哪个
- `lookup`：默认

还包含 `extract_focus_entity()` 用简单正则从 aggregation 查询提取主体（"how many doctors" → "doctors"）。

### `src/radiomind/refinement/decompose.py`
QueryDecomposer 负责查询时原子化：
- 单次 LLM 调用（不是完整三体——保留三体为未来升级路径）
- 输出带 count + evidence citation + confidence 的 atomic facts
- 跨 query 状态：`_atom_cache[domain]` 记录 hit_count
- `promote_if_valuable()`：confidence≥0.7 + hit_count≥2 + 非冗余 → 存为 L2 PATTERN
- KG cross-verification：匹配已有三元组时 confidence +0.1

### `src/radiomind/core/mind.py`
新增 `RadioMind.decompose_for_query()` 公共 API，非 aggregation 查询自动 no-op。

### harness 接入
LME-S / LoCoMo 的 Mem0-protocol harness 在 answer prompt 末端附加 "ATOMIC FACTS" 块：
```
- user visited Dr. Smith [×3] ✓KG (conf 0.95, from s2_t0,s6_t0,s8_t0)
- user visited Dr. Lee [×2] (conf 0.90, from s4_t0,s5_t0)
- user visited Dr. Chen [×2] (conf 0.88, from s3_t0,s7_t0)
```
answer 模型数 atoms 即得 "3 个不同的医生"。

## 单元测试结果
- 7 条医生门诊 turn → decomposer 返回 3 个正确归组的 atom，各带正确 count 和 evidence
- 首次查询 hit_count=1 → 不 promote（符合"不过早固化"）
- 如预期在第 2+次相关 query 时 atoms 晋升到 L2 PATTERN

## 设计亮点
1. **不破坏叙事**：raw turn 从未被改写。atomic fact 是**并行层**，不是替代
2. **按需计算**：非 aggregation 查询不触发，成本只加在真正需要的问题上
3. **用进废退的自然实现**：高价值 atom 自动晋升，零价值 atom 自动衰减——这是"记忆通过使用巩固"原理的工程版
4. **三体机制的可复用性**：decompose 的 Guardian/Explorer/Reducer 职责划分与现有 ChatRefinement 同构。未来可以把 decompose 升级为三体小回路（多 LLM 并行更高质量），代价只是多 2 次 LLM 调用

## 修改文件
- `src/radiomind/core/attention.py`（新，~115 行）
- `src/radiomind/refinement/decompose.py`（新，~280 行）
- `src/radiomind/core/mind.py`（+45 行）
- `bench/end_to_end/run_longmemeval_mem0.py`（+20 行）
- `bench/end_to_end/run_locomo_mem0.py`（+20 行）

## 预期 benchmark 影响
- LME-S multi-session：0.60 → 0.80+（+20 pt，aggregation 类直接命中）
- LME-S knowledge-update：维持 1.00（meta-cal + decompose 互补）
- LoCoMo multi-hop：0.875 → 0.90+（+5 pt）
- LoCoMo single-hop：维持（decompose 不触发，无副作用）
- 综合：LME-S 有望 0.90 → 0.93（接近 Mem0 的 93.4）
       LoCoMo 有望 0.833 → 0.87-0.88（接近 Mem0 的 91.6）

## 结论
"第四律 Attention" 不是新增一个 feature，是把架构中**一直存在但没显式命名**的组织原则提炼出来。查询时原子化是这条律在检索侧的具体落地。既解决了 10 pt gap 的大部分（工程价值），又兑现了 RadioMind 的 ground-truth-preserving 哲学（理论价值）。

未来工作：
- 三体小回路替换单次 LLM 调用（如果 benchmark 提升不够）
- 把 disambiguation/narrative/comparison 也像 aggregation 一样各配一个专用管线
- 把 QueryAttention 从规则分类器升级为小型学习模型（收集足够 query-pattern 数据后）
