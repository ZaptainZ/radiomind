# SmallUserReadiness-1b — 单域多样性前验 + narrow_adapter（不改 gate/classifier）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: 1a 判定 F2 过严阻断。用户裁决: 先做"单域是否可安全训练"前验,不改 L1 gate/
> 不扩 DOMAIN_KEYWORDS/不碰子串 bug（留 1c）;multi-domain 路径不变;单域仅多样性过线才允许;
> metadata+CLI 标 narrow;不 benchmark。

## 1. 实现
- **`src/radiomind/training/diversity.py`（新,纯函数）**: `diversity_report(sources,
  habit_count)` → habit_count / example_count / distinct_sources / **distinct_concept_tokens**
  （content-word 词汇量）/ near_dup_ratio（源文本两两 jaccard≥0.8）;`narrow_training_ok(report)`
  → near_dup ≤50% **且** 词汇量 ≥12 才允许。
- **data_gen**: `≥2 domains` guard 放宽——examples/habits guard **无条件先行不变**,仅当
  恰好 1 domain 且 examples+habits 已达标时,跑多样性前验: 过线 → `narrow_adapter=True`
  允许训练;不过线 → refuse 并说明（"too repetitive X%" / "too narrow N concepts"）。
  domains≥2 路径**逐字不变**,domains=0 仍 refuse。
- **关键修正（探针发现）**: 多样性必须测**源文本**（habit 描述 + facts）而非生成示例——
  data_gen 为每 habit 生成多个改写变体,示例间 near-dup 天然 81%,会把丰富源误判单调。
  改为累积 `source_texts` 度量。另: 弃用 lead-token（habit 描述都以"The user…"开头,
  lead token 恒为"user"→distinct=1 误判）,改用词汇量。
- **贯通**: `DataGenReport.narrow_adapter` → `TrainResult.narrow_adapter` → adapter 旁
  `train_meta.json`（`narrow_adapter` + `domain_count`）;CLI train/data-only 成功时
  黄字提示"NARROW adapter: single-domain, 不代表泛化个性"。

## 2. 验证
- `tests/test_diversity_narrow.py`（11）: 多样性度量（distinct sources/词汇量/near-dup
  正负例）、narrow gate（diverse 过/repetitive 拒/词汇少拒）、报告与 TrainResult 字段、
  **2 个集成测试**（真实 TrainingDataGenerator + stub 单域 store: diverse → narrow=True
  且 ex≥30;并锁定"多样性测源非增强示例"）、源码守卫（domains==1 分支/examples 先行）。
- pack 新增 `training:diversity-narrow` → **33 类全绿**;全量 **1022 passed**。
- **集成实证**: 6 条多样单域 habit/fact → refused=False, narrow=True, 47 examples, 6 habits,
  1 domain;同构 6 条重复 → refused（examples 先撞,符合"narrow 不放宽 examples/habits"）。
- **CLI re-smoke（8 样本）**: 正确走 F1 三项 gap（habits 0/5, domains 1/2, examples 1/30）——
  narrow 未触发,因 habits/examples 未达标（narrow 只放宽 domains,行为正确）。

## 3. 回答"单域训练是安全降级还是过拟合"
**有条件安全**: 单域只在 (a) examples≥30 + habits≥5（无条件,不降）且 (b) 源词汇量≥12 +
near-dup≤50%（防单调过拟合）时允许,且产物标 narrow_adapter,CLI 明示只适配当前主题。
单调单域（重复陈述）被多样性前验或 examples guard 挡下。**不是无条件放行,是带护栏的降级。**

## 4. 完成标准对照
- 8 样本多样性报告 ✓（CLI gap + 集成测试度量）
- 单域训练定性: 安全降级（带多样性护栏）✓
- narrow 实现: multi-domain 不变 ✓ / 单域仅过线允许 ✓ / metadata+CLI 标 narrow ✓
- 单测 + 集成 + re-smoke 通过 ✓（1022 / pack 33）

## 5. 不做 / 守住（留 SmallUserReadiness-1c）
未改 L1 gate、未扩 DOMAIN_KEYWORDS、未修 `work⊂network` 子串 bug、未训练真 LoRA、
未 benchmark。narrow 不降 examples/habits 门槛,只放宽 domains 且加多样性护栏。
