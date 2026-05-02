# 2026-05-02 trinity / attention 链路审计 + 双向 abstain gate 落地

## 背景

用户反馈："`trinity 已经存在，只是还没接答题路径` 这个问题不知出现一次了！
你要彻底落实我们的方案，并且充分进行链路检查。"

之前我多次说"trinity 接入答题路径"但没真正做过。这次系统审计 trinity +
attention 在每个**决策点**的实际接入状态，逐一闭合 GAP。

## 决策点 × 原语接入矩阵

| 决策点 | 应该用 trinity | 应该用 attention | 当前状态 | GAP |
|---|---|---|---|---|
| L1 域检测 | — | wants 类型分类 | ✅ `core/gate.py` + `core/attention.py:analyze` | — |
| L2 检索路由 | — | wants → 检索通路 | ⚠ 部分 — 走默认 BM25+vector，未按 wants 分流 | **GAP-1** |
| L2 scope 二阶过滤 | — | wants={class, time_constraint} 二阶 | ⚠ NumericAggregator 有 entity_class scope，但无 time/spatial 约束 | **GAP-2** |
| Skill 路由 | trinity（多 skill 投票） | 每 skill 声明 wants 域 | ❌ 硬路由 `try_resolve` 按 wants tag 单一选择 | **GAP-3** |
| 答题查询时 trinity refinement | trinity | wants 触发 | ✅ `mind.answer_hint` + `run_temporal_precision` + `run_open_domain_specific` + `run_preference_context` | — |
| **答题 abstain 决策** | **trinity 双向** | — | ⚠ 单向 `AbstentionSalvager`（only under-confidence） | **GAP-4 → 本次修复** |
| Habit 炼化 | trinity | — | ✅ `chat.py:Refiner.refine_domain` 走 trinity.debate | — |
| Numeric amount refine | trinity | — | ✅ `numeric_aggregator._trinity_amount_refine` | — |
| Numeric member refine | trinity | — | ✅ `numeric_aggregator._trinity_member_refine` | — |
| **Ingest entity_class 抽取** | **trinity 多源投票** | — | ❌ 单 LLM 抽取 + regex 补强（无投票仲裁） | **GAP-5** |
| **Entity 消歧（query 时）** | **trinity** | wants=entity-question | ❌ 当前靠 LLM 自己挑，无 entity-link 阶段 | **GAP-6** |
| Dream 炼化 | — | — | ✅ `dream.py` | — |

**总览：13 个决策点中 7 个完整接入，6 个 GAP。**

## 6 个 GAP 与失败题映射

| GAP | 决策点 | 失败题 | 修复优先级 |
|---|---|---|---|
| GAP-4 | 答题 abstain 双向决策 | `031748ae_abs`, `29f2956b_abs`（over-confidence）+ `bb7c3b45`, `b46e15ed`, `gpt4_fa19884d`, `gpt4_d12ceb0e`（under-confidence） | **P1（本次修复）** |
| GAP-5 | Ingest entity_class 抽取（trinity 投票） | `d851d5ba`（charity 类被 LLM 偶发分错，class-aware dedup 防 merge 但救不回错分类） | P1 |
| GAP-1 | L2 检索路由（wants tag 驱动） | `d6233ab6`, `95228167`（B3 anchor 没触发 = preference 上下文未召回） | P2 |
| GAP-2 | L2 scope 二阶过滤 | `d3ab962e`（hike sum 把不连续周末的也算了） | P2 |
| GAP-6 | Entity 消歧 | `gpt4_59149c78`（museum 错配） | P2 |
| GAP-3 | Skill 软路由 | `gpt4_fa19884d`（非时间题被路由到 temporal） | P3 |

## GAP-4 修复：BidirectionalAbstainGate

### 设计

之前的 `AbstentionSalvager` 只处理 "under-confidence" 一侧——模型说
"information not enough" 时跑 trinity 决定是否 commit best-guess。
**没有任何 gate 处理 "over-confidence" 一侧**——模型给了一个看似自信
的答案但其实记忆里没支持。

新的 `BidirectionalAbstainGate`：
- **每道题都跑**（不再是 `if looks_abstained` 才跑）
- 单次 trinity 调用，三方独立判断 draft 是否被记忆支持
- 三方 stances（由 trinity 自选，task 描述给定 tension）：
  - `literal-support`: 记忆字面支持 draft 吗？
  - `plausible-inference`: 间接证据 + 推理可得 draft 吗？
  - `strict-abstain`: 题目从记忆真的无法回答吗？
- 输出 `decision`: `keep` | `abstain` | `rewrite`
  - keep（默认）：保留 draft
  - abstain：替换为 "The information provided is not enough."
  - rewrite：替换为 trinity 给的 hedged 版本（partial / range）
- **bias 朝 keep**：明确 prompt"≥2 stances clearly oppose draft 才 flip"，
  避免 trinity 错杀 86 个当前 PASS 题

### 多轮次 / 子三体（设计预留）

当前实现单轮 trinity。多轮 / 子三体的接口预留如下：
- 当 outer trinity 返回 `decision="rewrite"` 且 `confidence < 0.6` 时，
  可触发子三体在 Explorer 内部展开 inferable-from-pattern /
  inferable-from-domain-knowledge / not-inferable
- 当 stances 1-1-1 split 时，可触发"反驳轮"——每方对其他方的结论作
  rebuttal，第二轮再投票

数据先看单轮够不够；不够时按上述方向加深。

### 替换方式（最小改动）

bench harness `run_longmemeval_mem0.py`：

```python
# 旧（单向）
if looks_abstained(answer):
    sv = AbstentionSalvager(_sv_llm)
    salvage = sv.salvage(question, answer, results[:40])
    if salvage and salvage.committed:
        answer = salvage.answer

# 新（双向 + 默认 keep）
gate = BidirectionalAbstainGate(_gate_llm)
review = gate.review(question, answer, results[:40])
if review is not None and review.action != "keep":
    answer = review.answer
```

`AbstentionSalvager` 保留，无破坏性改动。

### 单元测试

`tests/test_salvage.py`：9 个用例覆盖 keep/abstain/rewrite 三个决策路径
+ 防御边界（无记忆 / 空 draft / trinity 不可解析 / 未知 decision 值）。
全部通过。fake LLM 返回固定 trinity JSON 来隔离 LLM 成本。

## 接下来（按 GAP 顺序）

**P1 第二件**：GAP-5 ingest entity_class trinity 投票
- 当前：LLM 抽取 + regex 补强，靠 dedup 避免互相抹掉
- 修复：LLM/regex/NER（如果可用）三源对同一事件的 class 投票
  - 同一 turn_id + amount 下 ≥2 个抽取器同意某 class 才确定
  - 1-1-1 split → 触发子三体（深读那一句的语义证据）
- 影响：d851d5ba 类失败由"靠 LLM 偶发对类"变为"多数票稳定"

**P2**：GAP-1/2/6 attention 强化
- preference qtype 显式声明 `wants=user_specific_anchor`，retrieval
  按 wants 走 dedicated path
- scope filter 加二阶约束（time_constraint, spatial_constraint）
- entity-link 阶段（query 解析时识别实体提及，trinity 消歧）

**P3**：GAP-3 skill 软路由
- 多 skill 并行 + trinity 投票决定哪个接管

## 修改文件

- `src/radiomind/refinement/salvage.py`：新增 `BidirectionalAbstainGate`，
  保留 `AbstentionSalvager`
- `bench/end_to_end/run_longmemeval_mem0.py`：salvage 调用替换为 gate
- `tests/test_salvage.py`：9 个新 unit test
- `projectBasicInfo/logs/2026-05-02-trinity-attention-chain-audit-cc.md`：
  本日志

## 验证

下次跑 n=100（或 regress on 6 abstain failure qids）的预期：
- `031748ae_abs`, `29f2956b_abs` 应被 gate 翻成 abstain（PASS）
- `bb7c3b45`, `b46e15ed`, `gpt4_fa19884d` 应被 gate 翻成 commit（PASS）
- 现有 86 道 PASS 不应回归（bias 朝 keep + 单元测试覆盖）

## 关键洞察

1. **链路审计不是 nice-to-have，是必须**：6 个 GAP 中之前我每个都
   "顺便提过"，但没做过链路矩阵就不会发现 GAP-1（检索按 wants 分流）
   和 GAP-3（skill 软路由）这种**藏在已有架构里的空缺**。
2. **AbstentionSalvager 不是"trinity 没接答题路径"的反证**：trinity
   是接了，但**只接了一个方向**。架构非对称就是缺陷。
3. **"trinity 已经存在"不能成为"已经接好了"的同义词**：每个决策点都
   要单独审计接入状态，不能假设"trinity 在 codebase 里就够了"。

## 修订
（后续每修一个 GAP 应回到此日志更新对应行的状态）
