# 2026-05-13 V7 Step 0+1+2: evidence-candidate injector — 替代 V6.6.p2 prompt hint

## 背景

V6.5 + V6.6 全系列（11 次独立 10-qid smoke 跑）全部 4-6/10，看似都在 LLM 噪声地带。但用户后续诊断指出三层信号 was being conflated：

1. **judge 不一致**：c2 Maria V6.3 是 judge SSL error 误 FAIL；c1 Gina V6.3 "Feb 8, 2023" 被judge 接受为"a few years ago"；c3 big screen "three" 被 judge 接受为 "two"；c3 Nate "Lord of the Rings + 提到 dragon image" 被某些版本算对；c5 Voyageurs "no specific park" 被算对
2. **方向对但实现粗**：V6.6.p2 memory-signal regex 是对的方向，但只输出 `dominant_signal=proper_noun → form=named_entity` 这种 prompt hint，让 answer LLM 自己再解释，noise 大
3. **题干元判定方向错**：V6.5 系列 LLM trinity 判 simple/complex 不稳，跨次 retry-consistency 4/10 fails

## V7 三步路线（用户审批）

```
Step 0 (前置, 0.5d)  修 strict judge: 去噪后真实基线
Step 1 (1-2d)       V6.6.p2 升级 evidence-candidate injector
                      输出 {candidate, quote, relation, temporal_role, confidence}
                      injection 进 retrieved 槽位, 不进 prompt 顶部 directive
                      每题建 fixture: candidate set 必须含 gold 关键 token
Step 2 (1d)         trinity 改为 candidate-convergence 模式
                      agent_role="candidate-convergence-resolver"
                      stances = [conservative-evidence-only, inferential-allowed, exact-quote-required]
                      只在 candidate count ≥ 2 时启动
Step 3 (并行)        c1 + c6 走方向 A 子集: ingest-time temporal role tagging
                      只先做 "relative-temporal expression" 这一种
```

## Step 0 实施

### 文件
- `bench/end_to_end/strict_judge.py` (新): deterministic 重判 LLM bench 结果
- `bench/end_to_end/validation/strict-rejudge-v6.3-v6.5.3-v6.6.p2.txt` (新): 重判输出

### Strict judge 规则
- 抽 final answer section（`\\bANSWER:\\b` 之后）；若无显式 marker 则视为截断，用 body match 模式
- refusal 检测仅作用于 final section（不在 reasoning 段误伤）
- 日期：YYYY-MM-DD / Month DD, YYYY / 相对短语（"a few years ago/before/earlier"）
- 计数：词数(one/two/.../first/.../third) 排除 Step N、年份 4 位、日期
- 财务等抽象状态：positive (`middle-class|wealth|stable|secure`) vs negative (`strain|unstable|job loss`)，word-boundary 防止 `stable` 误匹配 `unstable`
- 每题专用规则函数（10 个 qid 全部覆盖）

### 实测结果

11 次独立 10-qid smoke 跑的 3 个代表版本，重判去除 judge 偏置：

| 版本 | LLM Judge orig | Strict re-judge |
|---|---:|---:|
| V6.3 baseline       | 5/10 | **4/10** |
| V6.5.3 (题干 trinity 强化) | 5/10 | **2/10** |
| V6.6.p2 (memory signal) | 6/10 | **4/10** |

**核心发现**：
- V6.3 与 V6.6.p2 在 strict 下打平 4/10（V6.6.p2 原 6/10 中 2 道是 judge 误判）
- V6.5.3 strict 2/10 = LLM 题干元判定**主动伤害**模型（救 1 倒 3）
- V6.3 vs V6.6.p2 差异：V6.3 win c4 Seattle，V6.6.p2 win c1 Gina（1-vs-1 交换，非整体增益）

判定 judge 不一致**主导了 11 次跑的噪声**：相同 LLM 在不同版本上对相同 answer 给不同 verdict（c1 Feb 2023 答案被 3 个版本分别给 PASS/FAIL/PASS）。

## Step 1 实施

### 文件
- `src/radiomind/core/evidence_candidates.py` (新): 主模块
- `tests/test_evidence_candidates.py` (新): 19+ 单元 + 10 fixture 测试
- `src/radiomind/core/mind.py`: 新增 `run_evidence_candidates()` wrapper（unconditional fires for ALL queries）
- `bench/end_to_end/run_locomo_mem0.py`: bench prefix 加 `evidence_section`

### 设计要点
1. **首类结构化候选**：`EvidenceCandidate {candidate, quote, relation, temporal_role, confidence, source_count, source_dates}`
2. **零 LLM cost**：完全 deterministic regex extraction
3. **query-type 路由**：when/how_many/where/what_about/what_doing/might_be/which 等 8 类
4. **过滤 query subject**：query 中的 proper noun 自动排除（answer 不是问题中的主语）
5. **过滤 stopword**：`my, his, her, the, a, ...` + 月份/星期 不当 entity

### 替换点
- 之前 V6.6.2 multi-view directive 在 `answer_hint` 内部，仅 date/inference query 触发
- V7 Step 1 提到独立 wrapper `run_evidence_candidates`，**所有 query 都触发**（包括 single-hop）
- `answer_hint` 内已 revert 为 trinity-only，去除原 V6.6 hint

### Fixture 测试结果（10 个 qid）

| qid | 期望 | 实际候选集 |
|---|---|---|
| c1 Gina | relative phrase | ✓ "a few years ago" with `temporal_role=relative` |
| c2 Maria | Aug 4 2023 | ✓ "2023-08-04" |
| c2 financial | positive indicator | ✓ "comfortable", "savings", "investments" |
| c3 count | count tokens | ✓ "first/second/third" |
| c3 Tilly | "Tilly" | ✓ "Tilly" (Joanna filtered as query subject) |
| c3 Nate | "dragons" | ✓ "dragons" (topic keyword) |
| c4 Seattle | "Seattle" | ✓ "Seattle" |
| c5 Voyageurs | "Voyageurs" (when present) | ✓ "Voyageurs" + 不假阳性 |
| c6 Sept 2022 | "September 2022" | ✓ "September" + "2022-09" |
| c9 Calvin/Dave | 抽象美德 | ✓ candidates 非空 |

19 个 classify + 单测 + render 测试全过；总 409 测试全过。

## Step 2 实施

### 文件
- `src/radiomind/refinement/trinity.py`: 新增 `_AGENT_ROLES["candidate-convergence-resolver"]` 一阶参数
- `src/radiomind/core/evidence_candidates.py`: 新增 `converge_candidates_via_trinity(query, candidates, llm)` 函数

### 设计要点
1. **门控**: 仅在 `len(candidates) >= 2` 时启用（单候选无需收敛）
2. **三 stance**:
   - CONSERVATIVE-EVIDENCE-ONLY: 拒绝任何推断，picky pickle the candidate whose quote literally states the answer
   - INFERENTIAL-ALLOWED: 允许 'next month' → 'September' 这种合理推断
   - EXACT-QUOTE-REQUIRED: 只接受 quote 含 answer phrase 字面的 candidate
3. **锚点恢复**：trinity 不再做 simple/complex 元判定（无锚），而是在多个 candidates 之间收敛（有锚 = 候选集）

### 状态
- Step 2 module + agent_role + 3 单测全部完成
- **未 wire 入主路径** — 等 Step 1 smoke 结果再决定是否启用

## Smoke 验证状态

启动 V7 Step 1 在 1 qid (c3_94f06e1a00 Joanna Tilly) 上的 LoCoMo bench smoke。

Pipeline:
- ingest LoCoMo c3 conversation → sandbox /tmp/rm-e2e-v7-step1-1qid
- 召回 → mind.run_evidence_candidates() 注入候选块
- deepseek-v3.2 answer with evidence block in prompt
- gpt-4o (openrouter) judge

期望对比：
- V6.3 baseline c3 Tilly: PASS (LLM 直接从 raw memories 找到 Tilly)
- V6.6.p2 c3 Tilly: PASS (dominant signal=proper_noun 引导)
- V7 Step 1 c3 Tilly: ? (deterministic candidate set 含 "Tilly")

## Open Decisions（结果出来后再定）

- **如果 V7 Step 1 c3 Tilly = PASS**: 跑完整 10-qid flip smoke 验证 set-level 改进
- **如果 V7 Step 1 PASS 但其他题数下降**: 选择性 fire（仅 single-hop named-entity 类）
- **Step 2 启用条件**: ≥1 个题在 Step 1 单候选有歧义、Step 2 trinity 收敛能裁决
- **Step 3 排期**: 候选层稳定后开始 ingest-time temporal tagging（c1 Gina relative-only）
