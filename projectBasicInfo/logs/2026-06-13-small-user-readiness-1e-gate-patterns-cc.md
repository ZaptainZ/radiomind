# SmallUserReadiness-1e — 高精度 practice pattern 补 gate 召回（窄,无 LLM）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: 1d 审计（英文动词集 gap,#5/#6 habit-worthy 被 regex miss,可窄规则救回）。
> 用户裁决: 只加 2-3 条泛化限定词锚定的高精度英文 pattern;assistant 硬过滤/门槛/
> narrow/1b/1c 不动;不引 LLM。

## 1. 改动（`src/radiomind/core/gate.py`,仅新增 2 条 pattern）
新增 `practice` 类别两条,**锚定泛化限定词**（for any / for every / at every / in every /
whenever）而非裸动词,覆盖两种语序:
```
\b(?:for any|for every|at every|in every|whenever)\b.*\bi\s+\w+   # 限定词在前
\bi\s+\w+.*\b(?:for any|for every|at every|in every|whenever)\b   # 限定词在后
```
- #5 "For any AI feature I add…" → 限定词在前命中。
- #6 "I validate inputs…at every boundary" → 限定词在后命中。
- 既有 pattern 全不动;assistant 仍 `role != user` 硬过滤。

## 2. 精度验证（新 pattern 单独判定）
正例 KEEP: #5 / #6 / "Whenever I deploy I run…"。
负例（新 pattern **单独不匹配**）: "I add salt to taste" / "I validate the form once" /
"I add two numbers together" / "I think it's raining"。
- 注: "I think it's raining" full-gate 仍 KEEP,但由**既有 opinion pattern**（`i think`）抓,
  **非本次 practice pattern**——属既有行为,1d/1e scope 外（改 opinion 会动既有规则,不碰）。
  本次新 pattern 对它零匹配,无过宽。
assistant 同文本仍 DROP ✓。

## 3. 端到端（CLI re-smoke,8 样本）
- ingest: **8 → 5 memories**（1a/1c 是 3）——达成"≥5/8"。
- Domains: **1（1a 误判）→ 2（1c）→ 3（1e: software/networking/ai）**——无退化,#5 的
  AI 习惯救回贡献新域。
- "I validate…" 被 keep（domain="?",无关键词命中——gate 目标已达成,域分类是另一层,
  不影响 keep）。
- 剩余若 refuse 只会因 habits/examples 数据量不足,**不再因 gate 漏明显习惯**。

## 4. 验证
`tests/test_gate_practice_patterns.py`（7）: 正例救回、新 pattern 单独不误收 4 负例、
assistant DROP、8 样本 ≥5 且 3 assistant 全 drop。pack 新增 `core:gate-practice` →
**35 类全绿**;全量 **1041 passed**（无回归）。

## 5. 完成标准对照
- 8 样本保留 3/8 → **5/8** ✓
- domain_count 不退化（→3）✓
- refuse 仅因 habits/examples,不因 gate 漏明显习惯 ✓
- pack + smoke 通过 ✓（1041 / pack 35）

## 6. SmallUserReadiness 线收口
冷启动三阻断点全处理: **domain 误判/全盲（1c）+ 单域硬拒（1b narrow_adapter）+ L1 gate
英文召回（1e）**。剩余为数据量本身（需用户多写）——非系统缺陷。LLM 二段判定（1d 选项 B/C）
待真实第一人称语料出现再评估,本线不引 LLM。

## 7. 不做 / 守住
未改 assistant 过滤 / 既有 pattern（含 opinion 的 "I think" 行为）/ habits-examples-domain
门槛 / narrow 规则。未引 LLM。新 pattern 刻意窄（限定词锚定),不追泛化召回。
