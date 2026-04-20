# 2026-04-20（晚）— Elegance refactor：三体还原为 primitive

## 背景与问题
S1/S2/S3 落地后用户指出代码 "油腻"：
> "三体探讨的本质是三方博弈，如果你将它们的角色钉死为三种，然后我说在涉及数学时，你又钉死三种，那么这是十分愚蠢的做法，这三种角色应该在不同的领域做属于那个领域的三种对立观点"

核心诊断：
- `refinement/query_pipelines.py` 的 `TemporalPrecisionPipeline` / `OpenDomainSpecificPipeline` 是两套平行硬角色类
- `refinement/numeric_aggregator.py` 的 `_guardian_verify_amounts` + `_reducer_dedup` 是硬编码 Guardian/Reducer 方法，各带 24/29 行 prompt 把角色名钉死
- `core/attention.py` 的 `is_numeric_cardinal` / `is_specific_detail_lookup` / `is_temporal_precision` / `is_open_domain_specific` 是 4 个平行的硬 classifier
- numeric_aggregator 代码 1714 行，其中 **329 行 docstring** 违反 CLAUDE.md "默认不写注释"，**108 行 ontology 数据** 内嵌模块，**220 行 prompt** 字符串

## 原则落地
1. **三体是原语**：`trinity.debate(task, evidence, llm)`，三方对立立场由 LLM 根据 task 张力自选，不写死角色名。计数任务可能是"保守/包容/合并"，时间任务是"锚点/链路/窗口"，开放推理是"字面/推断/弃权"
2. **Attention 是 signature**：`analyze(query) → AttentionSignature{focus, wants, aux_flags}`，一个函数覆盖全部类别。下游模块按 signature 路由而非按 N 个 boolean 判定
3. **数据与代码分离**：ontology 独立模块，用 `dict.fromkeys` 合并相同父类赋值
4. **docstring 只说 WHY**：方法体自解释的去掉 20 行段落保留 1 行

## 动作

### 新增
- `refinement/trinity.py`（101 行）—— 通用三方博弈原语，支持 `extra_schema` 让调用方声明所需输出字段
- `refinement/ontology.py`（80 行）—— ROLLUP + ALIASES 数据模块 + 两个 helper

### 删除
- `refinement/query_pipelines.py`（-263 行）—— 两个 Pipeline 类都是 trinity 的 task_description 不同的实例

### 重构
- `refinement/numeric_aggregator.py` 1714 → 1292（-422）：
  - `_guardian_verify_amounts` → `_refine_amount_events`（trinity + `extra_schema='revoke_ids'`）
  - `_reducer_dedup` → `_refine_members`（trinity + `extra_schema='final_members'`）
  - 删除 GUARDIAN_AMOUNT_PROMPT + REDUCER_DEDUP_PROMPT
  - BATCH_EXTRACT_PROMPT 132 → 41 行
  - docstring 329 → ~150 行
- `core/attention.py` 272 → 261（-11）：主 API 改为 `analyze()` + `AttentionSignature`，保留 `is_X()` 作 1 行兼容 wrapper
- `core/mind.py` 1241 → 1163（-78）：两个 `run_*` 方法合并为 `answer_hint()`，通过 `_task_description_for(sig, query, ref_date)` 把 AttentionSignature 翻译成 task description

## 代码量
| 模块 | before | after | Δ |
|---|---:|---:|---:|
| numeric_aggregator.py | 1714 | 1292 | **-422** |
| query_pipelines.py | 263 | 0 (删除) | **-263** |
| trinity.py | — | 101 | +101 |
| ontology.py | — | 80 | +80 |
| attention.py | 272 | 261 | -11 |
| mind.py | 1241 | 1163 | -78 |
| **净减** | | | **-593 行** |

功能完全保留：211/211 tests pass。

## Elegance 验证

**现状检查**：call site 里是否还有"钉死三角色"的残留？
- numeric_aggregator 的两个 refine：调 trinity 只传 task_description，由 LLM 决定立场 ✓
- mind.answer_hint: `_task_description_for` 只描述 task 张力（"anchor-based vs chain-based vs window-based"），不命名具体 stance ✓
- trinity.py `_PROMPT`：要求 LLM "Identify three opposing analytical stances a careful analyst could take on THIS task"——显式让 LLM 自选立场 ✓

**兼容**：旧 API (`is_numeric_cardinal`、`classify`、`run_temporal_precision`、`run_open_domain_specific`) 保留为 1-2 行 wrapper，bench harness / 历史测试无需改。

## 下一步
用同一组 5 道 LME-S multi-session 错题跑小样本回归：
- 预期 Q1 instruments 仍 PASS（LLM batch 路径没变）
- 预期 Q2 charity 可能改善（trinity 现在由 LLM 自选立场，可能比"Guardian 硬角色"更灵活地找到应该 revoke 的项）
- 预期 Q3 hikes 不变
- 预期 Q4 kitchen 不变或微调（trinity 对 member 列表的 dedup 立场选择不同）

如果 2/5 维持，refactor 是零成本；如果有任一改善，说明"让 LLM 自选立场"比"硬钉角色"效果更好。
