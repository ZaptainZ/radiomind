# 2026-05-03 Trinity stance 命名 = 结构压力（关键方法论发现）

## 背景

n=100 v4 实测 0.820 vs v3 0.860 = **-4 pt 回归**。8/10 共享 qid 上的退步是
v4 把 v3 正确的 confident draft **强制改写成 abstain**。

诊断指向 `BidirectionalAbstainGate` 的设计——但深挖后发现这不是简单的"代码
回滚"问题，而是**对 trinity 命名规则的一次重要发现**：

> **Trinity 的 stance 命名直接产生结构性偏差**。
>
> 按"结论"命名 stance（如 `strict-abstain`）会在 LLM 扮演时强迫它寻找
> 该结论的支持理由，无论真理在哪一边。"Bias to KEEP"这种 prompt 文字
> 提示远比不上**角色名字**所强加的结构压力。

## 实证数据：why over-abstain across 7 qids

7 道 v3 PASS / v4 FAIL 全是 confident-and-correct draft 被 trinity 翻成
"info not enough"：

| qid | v3 答案（正确） | v4 答案 |
|---|---|---|
| afdc33df | "Focus on your utensil holder..." | "info not enough" |
| 09d032c9 | "Since you own portable power bank..." | "info not enough" |
| caf9ead2 | "About 5 hours" | "info not enough" |
| 71017276 | "4 weeks ago" | "info not enough" |
| 6071bd76 | "less water per tbsp..." | "info not enough" |
| 778164c6 | "Grilled Snapper with Mango Salsa" | "info not enough" |
| gpt4_8279ba02 | "10 days ago" | "info not enough" |

我设计的 BidirectionalAbstainGate 的 trinity 内 stances：
```
- literal-support: does memory text DIRECTLY answer this?
- plausible-inference: can the answer be derived from indirect evidence?
- strict-abstain: is the question genuinely unanswerable from memories?
```

LLM 扮演 `strict-abstain` 时，**必须找 abstain 的理由**——即使 draft
正确、记忆显著支持。常见自洽借口：
- "措辞不是字面匹配"
- "需要推理才能得到这个答案"
- "记忆没显式说出这个数字/这个表述"

`literal-support` + `plausible-inference` 投票 keep 时，`strict-abstain`
搬上"不够显式"的论据 → 2-1 投票变成 1-2 投票（常见在 confident-correct
case）→ 实施 abstain 翻转。

## 与既有"对的" trinity 对比

`numeric_aggregator._refine_amount_events`、`chat refinement`、`age_interval`
锚点匹配等用 trinity 工作得好——它们的 stance 命名是**维度型**的：

| ✅ 工作良好的 trinity 命名 | 维度型 |
|---|---|
| `strict / inclusive / consolidative` | 评估力度 |
| `anchor-based / chain-based / window-based` | 时间推理方式 |
| `stability-first / novelty-first / parsimony-first` | 习惯优先级 |
| `literal-mention / semantic-paraphrase / abstain-if-thin` | 匹配类型 |

| ❌ 工作不良的 trinity 命名 | 结论型 |
|---|---|
| `literal-support / plausible-inference / strict-abstain` | 三个角色已经把结论写在名字里 |

注意第三种"abstain-safe"虽然名字含 abstain 但**前缀是动作而非结论**——
"abstain if evidence thin" 是个**条件**。"strict-abstain" 是个**结论**。
区别看起来微小但是结构压力极不同。

## 方法论新原则

**写进 `02_CORE_METHODOLOGY.md`：trinity stance 命名规则**

```
✅ 用维度命名 stance：每个角色只代表一种"看问题的角度"
❌ 不要用结论命名 stance：避免角色名包含 "commit/abstain/keep/revoke"
   等明确决策动词

判断标准：
- 把 stance 名字读出来，能猜到它会投什么票吗？
  - 能 → 结论型（错），它的投票被名字预定了
  - 不能 → 维度型（对），它的投票由证据决定

举例：
  ✅ "evidence-density-first" — 看证据密度（投什么取决于密度高低）
  ✅ "specificity-strict" — 看特异性（投什么取决于匹配程度）
  ❌ "commit-friendly" — 倾向 commit（票已定）
  ❌ "abstain-safe" — 倾向 abstain（票已定）
```

## 不对称的真正解释

为什么 `AbstentionSalvager` (under-confidence) 工作良好，而双向 gate
(over-confidence) 翻车？

| 方向 | draft 状态 | 真理位置 | strict-abstain 倾向 | 净效果 |
|---|---|---|---|---|
| Under-confidence | abstained | 应该答（推理可得） | 与 draft 相同（abstain） | literal+inference 联合压倒它，能反转到 commit ✓ |
| Over-confidence + 模型对 | committed | draft 正确 | 与真理相反 | 在 KEEP 应当胜出但 strict-abstain 用"不够字面"作论据，2/3 abstain ✗ |
| Over-confidence + 模型错 | committed (错) | 应当 abstain | 与 draft 相反但与真理一致 | 应该工作但 LLM 已经 commit，literal-support 找到论据替它辩护 ✗ |

**结论**：over-confidence 方向**两个失败模式都常见**——结构性偏差让正确
draft 被错杀，而错的 draft 又因 literal-support 的脱钩辩护而保住。

## 修复决定

**短期（commit 待定）**：salvage.py 加 `if not looks_abstained: return None`
guard，回到 v3 的单向 salvage。

**长期（待考虑）**：如果将来真要做"答非所问"检测，trinity 设计应当：
1. **不要**让某 stance 名字预设结论
2. **改用维度型**："evidence-density / specificity-match / contradiction-search"
3. 或者**根本不用 trinity**——这种"挑刺"任务本质单向（只是想反对），
   不真是三方平衡

## 检查 v3 的 prompt 中 v4 该借鉴什么

### 三处关键 prompt 改动对比

| 调用 | v3 → v4 改动 | 评估 |
|---|---|---|
| `run_preference_context` 内 trinity | output 加 "REQUIRED ≥3 concrete + verbatim" | stance 命名维度型（OK），但 output 过度约束。**本次未引发回归**，留观察 |
| `mind.answer_hint` multi-round | 单轮 → date+inference 都 3 轮 | **inference 的多轮是可疑元凶之一** |
| `AbstentionSalvager` → `BidirectionalAbstainGate` | only-abstained → every draft | **主要回归元凶**——已 guard 修复 |

### v3 借鉴一：`inference` qtype 不该 multi-round

`mind.answer_hint`：
```python
# v3 era (b2f5a60): single-round always
# v4 era (0095d50): debate_rounds = 3 if sig.wants in {"date", "inference"} else 1
# revert: debate_rounds = 3 if sig.wants == "date" else 1
```

**为什么** `inference` 不该多轮：
- `inference` = "what could / what should / who would" 等开放型问题
- 这类是**发散性**任务（无唯一对答案）——多轮让 round 2 看到 round 1 后
  "再努力一下"，常导致 round 1 正确 abstain 被改写为错误推断
- 实证：gpt4_93159ced_abs（gold expects abstain）v3 正确 abstain，v4 给了
  "estimate 4-5 years" 的推断
- `date` 不同——日期算术有唯一正确答案（收敛性），多轮值得用

### v3 借鉴二：Salvage 的"工作"靠的是使用条件，不是 trinity 本身

V3 的 `AbstentionSalvager` 用同样的 `literal-support / plausible-inference /
strict-abstain` 三 stances（同样命名问题），但**只在 draft abstain 时跑**——
这个使用条件**间接修正了 stance 命名的偏差**：

| Draft 状态 | 真理位置 | strict-abstain 倾向 | 净效果 |
|---|---|---|---|
| abstain（v3 的唯一触发条件） | 应当 commit | 与 draft 同向（无害） | literal+inference 联合压倒，commit 翻回 ✓ |
| confident（v3 不触发，v4 触发） | 应当 keep（draft 对） | 与真理反向（有害） | strict-abstain 找借口，2/3 投 abstain，错杀 ✗ |

**结论**：v3 借鉴的核心是它的**克制**——只在 draft 已经认输时才请 trinity
帮忙救一把，不在 draft 自信时找麻烦。

### v3 借鉴三：preference output 强约束保留观察

GAP-1 的 prompt 强化（"≥3 concrete + verbatim"）虽不是本次回归元凶，但
**理论上有过度约束风险**——如果某 preference 题的记忆里 user-specific
信号本来就少，强迫 trinity 凑 3 个会拉来弱细节甚至幻觉。当前没数据证明
有害，留作下次 n=100 监控。

## 修复决定

按"借鉴 v3 的克制"三步落地（一改一减一记）：

1. **改 `salvage.py`**：加 `if not looks_abstained: return None` guard
   （已实施 + 单测更新）
2. **改 `mind.answer_hint`**：`{"date", "inference"}` → `"date"` only
   （已实施）
3. **记 `02_CORE_METHODOLOGY.md`**：stance 命名规则 + 多轮适用场景
   （已实施）

预期 n=100 影响：
- 救回 7 道 over-abstain（gate 不再误伤 confident draft）
- 救回 ~1 道 inference 漂移（93159ced_abs 不再过度推断）
- 失去 2 道 over-confidence 翻转（031748ae_abs / 29f2956b_abs 退回 v3 的 PASS——但这俩在 v3 就 PASS 了，所以净中性）
- 实际净效应：v4 0.820 → 预期 ≈ **0.88-0.90**，与 v3 0.860 持平或略高

## 修改文件

- 本日志（先记录发现）
- 准备改：`projectBasicInfo/02_CORE_METHODOLOGY.md`（加入 stance 命名规则）
- 准备改：`src/radiomind/refinement/salvage.py`（短期 guard）

## 修订历史

- 2026-05-03 创建。源自 n=100 v4 - v3 = -4pt 的 root cause 调查。
