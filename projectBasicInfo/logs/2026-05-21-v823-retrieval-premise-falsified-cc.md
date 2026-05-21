# 2026-05-21 V8.2.3 deterministic retrieval — 前提被证伪

## 背景

Codex 建议 V8.2.3 做 relation-aware FTS 救 LME-S 中 2 个 V8.2.1 vs V6.1.1 的 retrieve regression：
- `9a707b82` chocolate cake
- `9aaed6a3` SaveMart $0.75

预设：V6.1.1 (KG enabled) retrieve 拿到 gold-bearing memory；V8.2.1 (KG disabled) retrieve 漏召，所以 LLM 答 "not enough"。

## 诊断结论：retrieve 没漏

实际跑 V8.2.1 sandbox 的 retrieve（同 protocol、同 query）：

| qid | gold memory rank | retrieve 是否含 gold |
|---|---:|---|
| `9a707b82` chocolate cake | **rank 4** in top 21 | ✅ 含 |
| `9aaed6a3` SaveMart $0.75 (chain) | **rank 1 + rank 3** in top 21 | ✅ 含 |

### chocolate cake (9a707b82)

V8.2.1 retrieve top 21 包含 gold memory at rank 4:
```
[lme_59] [user] I'm excited to try making croissants again...
By the way, I just baked a chocolate cake for my friend's
birthday party last weekend that turned out amazing.
```

LLM 看到了这条记忆但答 "The information provided is not enough."

**LLM 失败原因**：question 说 "a couple of days ago"，memory 说 "last weekend"。LLM 没认 "last weekend" ≈ "couple of days ago"（temporal-loose-match 失败）。

### SaveMart $0.75 (9aaed6a3)

V8.2.1 retrieve top 21 包含两条 evidence memories:
```
Rank 1: [user] I spent $75 on groceries at SaveMart last Thursday.
Rank 3: [assistant] Let's start with the $75 you spent at SaveMart last Thursday.
```

还有更早的 "1% cashback on all purchases" 记忆（在 session_2，也在 retrieve 里）。

LLM 看到了完整 evidence chain 但答 "not enough"。

**LLM 失败原因**：gold $0.75 = 1% × $75，需要 LLM 做 cashback rate × amount 的乘法。LLM 没做这个推理（arithmetic reasoning 失败）。

## V8.2.3 retrieval expansion 不解决这两题

- 两题都没有 retrieve miss
- V6.1.1 PASS 的真正机制可能是 KG atomic-fact / cardinal-cache / 其他 layer 给 LLM 提供了"$75 × 1% = $0.75"或"last weekend = recent days"提示
- 单纯加 relation-aware FTS 不会改变这两题的结果

## 真正瓶颈分类

| qid | 真实瓶颈 |
|---|---|
| `9a707b82` chocolate cake | LLM temporal-loose-match（"last weekend" 应认为 ≈ "couple of days ago"） |
| `9aaed6a3` SaveMart $0.75 | LLM cashback arithmetic（1% × $75 = $0.75 需 LLM 计算） |

## V8.2.3 应该重新定位

按 Codex 原则：不做宽面、不做 V6.2 expand-wide。针对**已诊断的真瓶颈**：

### V8.2.3a：cashback-rate × amount arithmetic helper（针对 9aaed6a3 类）

- 检测 query 是 "how much X did I earn at Y" + memory 同时含 amount + rate
- 注入 calculation hint："memory shows rate R + base amount A; product R × A = ?"
- 不是新 retrieve，是 answer-side hint

### V8.2.3b：temporal-loose-match（针对 9a707b82 类）

- 检测 question 含 "a couple of days ago / a few days ago / recently"
- memory 含 "last weekend / X days ago / yesterday"
- 注入 hint："loose temporal range — accept these mappings"

两个都是 **answer-side 微调**，不是 retrieve-side 扩展。**完全不同 layer**。

## 建议给 Codex/用户

V8.2.3 不应做 deterministic retrieval（因为没有 retrieve miss 可救）。两个真瓶颈都在 LLM answer 层：

选项 A：**放弃 V8.2.3**，承认这两题需要 LLM behavior 改造（risk: 像 V6.5 题干元判定一样宽面失败）  
选项 B：**V8.2.3a/b 做窄答题侧 hint**（cashback arithmetic、temporal loose-match），仅特定 query 模式触发  
选项 C：**先停下，做完整 retrieve-vs-LLM 失败分类**，看 V8.2.1 还有哪些 FAIL 是 retrieve miss vs LLM 推理失败，分别策略攻击

我倾向 C — 不应在没有完整分类前再加 layer。先确认 V8.2.1 失败分布，再决定 V8.2.3 / V8.2.4 路线。

## 文件

```
bench/end_to_end/lme-s-v82-1-n100.json — V8.2.1 baseline
projectBasicInfo/logs/2026-05-21-v823-retrieval-premise-falsified-cc.md (本文件)
```
