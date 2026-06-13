# SmallUserReadiness-1d — L1 gate 召回率审计（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: 1c 后冷启动剩 L1 gate 瓶颈。用户裁决: 只读审计,不改 gate,不让 assistant 进 fuel,
> 不引 LLM classifier,不降 habits/examples 门槛。≥2 真实 habit-worthy 被 regex miss 且可
> 窄规则/安全二段救回,才开 1e。

## 1. 规则盘点（实为 17 条,非 16）
| 类别 | zh | en |
|---|---|---|
| identity/preference/aversion/explicit/goal/routine/opinion | ✓ | ✓ |
| location / occupation / possession / event | ✓ | **✗ 无英文 pattern** |

- **强信号(高精度)**: identity / preference / aversion / explicit / goal — 动词锚定明确。
- **历史遗留风险**: `event` 仅 zh（`今天/昨天…(.{10,})`）宽松;英文侧完全缺 location/occupation/
  possession/event。
- **英文动词集固定且小**: like/love/prefer/enjoy、hate/dislike/avoid、want/plan/intend/need to、
  usually/always/often/every day、think/believe/feel that、my name is/i'm/i am、remember。
  → "I add / I validate / I write / I build / I cache / I deploy" 等当下习惯动词**全不匹配**。
- **assistant 硬过滤 = 正确,保留**: 习惯是关于用户的,assistant 回复不应进 habit fuel
  （审计确认,不动）。

## 2. 8 样本逐条判定表
| # | role | gate | 人判 | fail 原因 |
|---|---|---|---|---|
| 0 | user | KEEP | habit | — （"I always write…" 命中 routine） |
| 1 | assistant | drop | (habit-ish) | role — **正确**（assistant 不进 fuel） |
| 2 | user | KEEP | (弱) | — （"I always add" 命中 routine） |
| 3 | assistant | drop | no | role — 正确 |
| 4 | user | KEEP | habit | — （"I prefer" 命中 preference） |
| **5** | user | **drop** | **habit** | **regex-miss**（"For any AI feature I add…" 无白名单动词） |
| **6** | user | **drop** | **habit** | **regex-miss**（"I validate inputs…at every boundary" 无白名单动词） |
| 7 | assistant | drop | no | role — 正确 |

→ **3 assistant drop 全部合理**; user 侧 4 条 habit-worthy 中 **2 条（#5/#6）被 regex miss**。

## 3. live 大样本: 无法量化（关键诚实结论）
745 条 live store 内容跑 gate: KEEP 8 (1%) / MISS 737 (99%)——**但这是错误样本**:
live store 99% 是 RadioHeader/Shortwave **第三人称知识条目**（`[来源:X]` bug-fix 笔记,
经 `learn`/迁移**绕过 L1 gate**入库）,本就不是 gate 目标。筛第一人称子集: **仅 1/745**。
→ **RadioMind 至今实际用法是知识库（绕 gate）,不存在第一人称习惯对话语料,因此 gate
真实召回率无法从现有数据量化。** 这本身是产品事实: 习惯门的 recall 问题在真实第一人称
使用规模化前都是推断。

## 4. 判定: 8→3 是"部分合理 + 部分过严"
- 合理: 3 个 assistant drop（habits 不来自 assistant）。
- 过严: 英文当下习惯陈述（"I add/validate …"）因动词集固定被系统性漏 —— #5/#6 实证,
  **≥2 真实 habit-worthy regex-miss 门槛达成**（小样本,非大语料）。

## 5. 最小候选（不实现,待你定）
- **选项 A（推荐,确定性零风险）**: 加少量**高精度英文 pattern**,锚定**泛化限定词**而非裸动词,
  避免过宽: `i \w+ .*\b(at every|for any|for every|whenever|by default|in every)\b` 类 +
  curated practice 动词。#5("for any") / #6("at every") 正好被这种限定词锚定救回,且
  "I think it's raining" 不会误收（无泛化限定词）。**纯 regex,无 LLM,不碰 assistant。**
- 选项 B（LLM 二段,默认 off）: regex fail 的 user turn 交轻量 classifier 判 habit-worthy。
  无真实语料前不值得引入 LLM 复杂度。
- 选项 C（prepare-habits 内 LLM triage）: 同 B,仅在 prepare 内、默认 off。
- 选项 D（不动 gate,只改文案/数据量）: 过弱——英文动词集 gap 是结构性的,A 零风险应做。

## 6. 建议
开 **SmallUserReadiness-1e** 只做**选项 A**: 加 2-3 条泛化限定词锚定的高精度英文习惯
pattern + 单测（#5/#6 救回、"I think it's raining"/"I add salt to taste" 不误收、精度回归）。
**不引 LLM**（B/C 待真实第一人称语料出现再评估）。assistant 过滤、门槛、1b/1c 全不动。
门槛达成（≥2 可窄规则救回的 habit-worthy miss）→ 支持开 1e。

## 7. 不做 / 守住
本轮零代码。未改 gate / assistant 过滤 / 门槛。未引 LLM。live-store miss 率不作为
gate 过严证据（样本性质错配,已说明）。
