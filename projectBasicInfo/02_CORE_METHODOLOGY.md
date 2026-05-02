# RadioMind 核心方法论：trinity + attention

> "需要一轮三体时用一轮，需要多层用多层，需要多轮用多轮，需要多种利益
> 平衡则使用多方"——按需组合，不写死，无处不在。

RadioMind 只有**两个核心方法论原语**。所有其他模块（skills、retrieval、
NumericAggregator、entity-link、scope filter……）都是**系统设计**层的工具，
承担实现，可换可改，不假装是核心。

## 1. Trinity 三体辩论

**导入**：
```python
from radiomind import trinity
```

Trinity 不是固定 N 方的硬约定，而是**三个独立维度的可组合空间**：

```
        多方 (n_stances)        多轮 (max_rounds)       多层 (sub_trinity_depth)
        ─────────────           ──────────────          ──────────────────────
      2 = 对立双方            1 = 单轮（默认）         0 = 扁平（默认）
      3 = 三体（默认）        2 = 一次精化            1 = 弱 stance 内部再开 trinity
      4-5 = 多利益平衡        3 = 二次精化            ≥2 = 子三体可继续递归
      6-7 = 战略议会         （收敛即停）
```

### 何时用什么

| 场景 | 原语 | 为什么 |
|---|---|---|
| 路由判断 / abstain 决策 / skill 投票 | `trinity.fast` | 单轮三体，速度优先，1 LLM 调用 |
| 偏好上下文 / entity 消歧 / 类提升 | `trinity.balanced` | 两轮，单 round 有时漂；二轮足以稳 |
| 日期算术 / age interval / 多 hop 推理 | `trinity.deep` | 三轮 + depth-1 子三体，精度优先 |
| ROI/风险/流动性/机会 这类多利益 | `trinity.parties(4, ...)` | 三方不够，明确需要 N-party |

### API

```python
# 完整控制
trinity.debate(
    task: str,
    evidence: str,
    llm,
    *,
    n_stances: int = 3,           # 多方
    max_rounds: int = 1,          # 多轮
    sub_trinity_depth: int = 0,   # 多层
    converge_threshold: float = 0.7,
    extra_schema: str = "",
    max_evidence_chars: int = 6000,
    sub_trinity_threshold: float = 0.5,
) -> dict | None

# Profile 简写（覆盖 90% 的场景）
trinity.fast(task, evidence, llm)              # n=3, rounds=1, depth=0
trinity.balanced(task, evidence, llm)          # n=3, rounds=2, depth=0
trinity.deep(task, evidence, llm)              # n=3, rounds=3, depth=1
trinity.parties(4, task, evidence, llm)        # n=4, rounds=1, depth=0
```

### 输出 schema

每次返回（任何 profile）：
```json
{
  "stances": [
    {"name": "...", "emphasis": "...", "conclusion": "...", "confidence": 0.0},
    ...
  ],
  "final_answer": "...",
  "confidence": 0.0
}
```

加 `extra_schema=` 让 LLM 同时输出额外字段，如 `revoke_ids: [int]`、
`assignments: [{event_id, entity_class}]` 等。

### 收敛条件（多轮）

`max_rounds > 1` 时，每轮后检查：
- 所有 stance `conclusion` 字面相同（unanimous）→ 停
- 整体 `confidence ≥ converge_threshold` → 停
- 否则进入下一轮，把上一轮的 stances + final_answer + confidence
  注入 prompt，明确要求 reconsider

### 子三体递归（多层）

`sub_trinity_depth > 0` 时，每轮后检查每个 stance 的个体 `confidence`：
- 低于 `sub_trinity_threshold`（默认 0.5）→ 该 stance 内部开一个
  深度 `depth-1` 的子三体（"对这个 stance 的结论再三方辩论一次"）
- 子三体的 `final_answer` 替换该 stance 的 `conclusion`
- 子三体可继续递归（如果 depth 还够）

每个 stance 独立递归，不会指数爆炸——成本受限于"弱 stance 数 × 深度"。

### 实战命中

| 失败题 | profile | 修复机制 |
|---|---|---|
| 6e984301（9 周 vs 3 周） | `deep` (rounds=3) | round 2 看到 round 1 stances 后重审锚日期 |
| d6233ab6（preference 空） | `balanced` + prompt 强迫 | 二轮让 trinity 强制提取具体名词 |
| d851d5ba（charity 类丢失） | 单轮 + class promotion | trinity 在 ingest 投票分类 |
| gpt4_fa19884d（skill 路由错） | `fast` 软路由 | 多 skill 并跑，trinity 选最佳 |

---

## 2. Attention 注意力

**导入**：
```python
from radiomind import attention
```

每个层（L1/L2/L3/L4）声明自己的 `AttentionSignature`，查询时用
`attention.analyze(query)` 得到 wants 信号，下游层按 wants 路由。

### Signature 字段

```python
@dataclass
class AttentionSignature:
    focus: str | None        # 主题实体 ("guitars", "kitchen items")
    wants: str               # count / date / inference / detail / lookup
    answer_shape: str        # number / amount / date / list / sentence / ...
    aux_flags: dict[str, bool]
```

### aux_flags 现有信号

| flag | 触发 | 下游用途 |
|---|---|---|
| `disambiguation` | 时间 dis 词（former/current/原来/现在） | knowledge-update 选 LATEST |
| `enumeration` | aggregation 但非 count | list-all 路径 |
| `comparison` | better than / 比 / 哪个 | comparison skill |
| `preference_anchor` | recommend / should I / any tips | retrieval 触发 user-context 二次召回 |
| `temporal_constraint` | consecutive / between / during / in March | scope filter 拒绝 unfiltered cardinal sum |

### 何时新增 aux_flag

每个新失败模式如果是"特定 wants 类别下的次级路由分支"，应当作为
新的 aux_flag 加进 `attention.analyze`，而不是在调用处单独写正则。
这是 attention 的"无处不在"原则——新维度统一从这里发出，下游订阅。

---

## 3. 调用模式：随处可用

### 在新代码里用

任何模块需要决策时：
```python
from radiomind import trinity, attention

# 路由 + 决策
sig = attention.analyze(query)
if sig.aux_flags.get("preference_anchor"):
    result = trinity.balanced(
        task=f"Extract user-specific anchors for: {query}",
        evidence=memories_text,
        llm=self._llm,
        extra_schema='  "context_items": [str, ...]',
    )
```

### 在已有 skill / refinement 中升级

把 `from radiomind.refinement.trinity import debate` 改成
`from radiomind import trinity`，按需切换 profile：
- 默认 `trinity.fast` 等价于旧 `debate(...)` 单轮
- 精度敏感的换 `trinity.balanced` / `trinity.deep`

### 不要在 skill 内部硬路由

每个 skill 仍然自己 `match(signature)`，但**多 skill 都 match**时
让 `try_resolve_soft` 跑 trinity 投票（已是 `mind.answer_hint` 的默认
行为）。skill 自己不需要写消歧逻辑——trinity 在外层兜住。

---

## 4. 不该用 trinity / attention 的地方

- **纯工程修复**：errata filter、数据集校验、deterministic 单测——
  这些不是决策点，不需要原语
- **明确的算法实现**：regex / FTS / 向量计算——这些是工具层，trinity
  不替代它们，只在它们之间投票
- **用户输入的直接 echo**：用户说什么就存什么的环节不需要 trinity
- **单一来源能确定的事实**：比如 user_id、时间戳，没有"多方对立"

---

## 5. 历史决定

每个新决策点，开发者需先回答：
1. **是不是决策点？** 输入 → 输出有歧义 / 多种合理答案 → 是
2. **是 trinity 还是 attention？** 在多个候选里挑（trinity）vs 路由分发（attention）
3. **trinity 的 shape？** 速度（fast）vs 精度（balanced/deep）vs 多方（parties）
4. **不在工具层假装 methodology**？ 如果是，明确标记纯系统设计

只有 1 + 2 + 3 都说清楚，再写代码。这是这个项目避免"prompt 表面修补"
和"硬路由堆补丁"的核心纪律。

---

**变更历史：** 2026-05-02 创建。trinity 多层（sub_trinity_depth）+ 多方
（n_stances）+ profile 简写在 commit `0095d50` / 后续提交中实现。
