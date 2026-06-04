# LME-S n=100 — current-main formal baseline refresh (2026-06-04)

> 作者: Claude Code (cc) ｜ 日期: 2026-06-04
> 类型: formal baseline run（authorized）。不开 fix，不边跑边改。LoCoMo 未跑（historical-only）。

---

## 1. 背景与目的
PX-1/PX-2 都是 dev tooling、未改 runtime。工具链（JAB / AnswerRetry / target-pack /
devtools / regression-pack）已成熟，做一次 **current-main LME-S n=100 正式刷新**，建立
新的 current-main artifact（README 公开分早已标 historical，此跑不是救文档，是立基线）。

## 2. 配置
- benchmark: LongMemEval-S (cleaned), n=100 stratified across 6 types
- answer: deepseek-v3.2 / dashscope
- judge: gpt-4o / openrouter
- mode: a2a-practice（current-main 原生默认；reranker ON，refinement ON）
- sandbox: `/tmp/rm-sandbox-lme-s-n100-refresh`（不污染 `~/.radiomind`）
- errata: 跳过 1 个 audited-bad gold（370a8ff4）
- elapsed: 45269s (~12.6h)
- 跑前 gate: regression_pack 18 类 ALL PASS；target-pack --report 解析正常
  （旧 artifact 的 2 个 required 红是已知 `[answer error: urlopen]` infra 假红）

## 3. 结果

| 指标 | 值 |
|---|---|
| **overall / raw / judged accuracy** | **0.910 / 0.910 / 0.910** |
| judge_errors / judge_error_rate | **0 / 0.0** |
| model_correct / judged_n | 91 / 100 |

**clean vs infra-adjusted**: raw = judged = 0.910，judge_errors=0 →
**完全 clean，无 infra 污染，无需任何 infra-adjust / rejudge / retry。**
0.910 即真实 current-main 分数。

### by qtype
| qtype | n | acc |
|---|---:|---:|
| knowledge-update | 16 | 1.000 |
| single-session-user | 16 | 1.000 |
| single-session-assistant | 17 | 0.941 |
| temporal-reasoning | 17 | 0.882 |
| single-session-preference | 16 | 0.875 |
| multi-session | 18 | 0.778 |

### artifacts
- `bench/end_to_end/lme-s-n100-2026-06-04-baseline.json`（per_query 全量）
- `...baseline.json.checkpoint.jsonl`（断点续跑记录）
- `...baseline.run.log`（里程碑日志）

## 4. Fail 归因（9 fails，preliminary，未逐个跑 diagnose）
用 `diagnosis_report.classify_preliminary` 对全部 fail 做 verdict 级归因
（devtools batch index 是 manifest-scoped，只覆盖 10 个 target qid，故对全 100 fail
改用直接抽取）：

- family: concrete-wrong-candidate ×5, abstain-no-hint ×4（**judge-infra=0, answer-error=0**）
- by qtype: multi-session ×4, preference ×2, temporal ×2, single-assistant ×1

| qid | qtype | 现象 | 家族 |
|---|---|---|---|
| 9ee3ecd6 | multi-session | 300 vs gold 100 | cardinality/numeric |
| gpt4_194be4b3 | multi-session | 乐器计数 | cardinality |
| gpt4_ab202e7f | multi-session | 4 vs gold 5 | cardinality |
| d3ab962e | multi-session | numeric recall (8 miles) | numeric recall |
| gpt4_d6585ce8 | temporal | 演唱会顺序 | OrderedEventList (PARKED) |
| b46e15ed | temporal | abstain | event-cluster-interval (PARKED, observe-only) |
| 778164c6 | single-assistant | abstain (菜名召回) | retrieval recall |
| 1c0ddc50 | preference | 主观偏好 | subjective preference (结构地板) |
| d6233ab6 | preference | 主观偏好 | subjective preference (结构地板) |

**结论（fail 家族）**: 9 个 fail 多落在 DEV_WORKFLOW §5 的 PARKED / 结构地板家族
（cardinality / subjective preference / ordering / 时间召回），且 judge-infra=0 /
answer-error=0（无 infra）。**但"fail 落在 parked 家族" ≠ "零 regression"** —— 见 §5
的 V6.1.1 直接对照：其中 4 个是 correct→wrong 的真实 regression，不能因家族眼熟就忽略。

## 5. 与 V6.1.1 直接对照（**同一 100 qid，同顺序** — 已核对 artifact）

对照文件: `lme-s-n100-2026-06-04-baseline.json` vs
`lme-s-n100-v6.1.1-deepseek-judge4o.json`。脚本核对结果:
`same set=True, same order=True` —— **不是不同抽样**，是同一题集的逐题对照。

| | V6.1.1 | current-main | Δ |
|---|---:|---:|---:|
| accuracy | 0.930 | 0.910 | **−2pt** |

**Direct composition（per-qid flip）**:

| 类别 | n | qids |
|---|---:|---|
| **FIX** (V6.1.1 wrong → now right) | 2 | `d851d5ba`, `c18a7dc8` |
| **REGRESS** (V6.1.1 right → now wrong) | 4 | `9ee3ecd6`, `1c0ddc50`, `gpt4_194be4b3`, `d3ab962e` |
| **BOTH FAIL** | 5 | `b46e15ed`, `778164c6`, `gpt4_d6585ce8`, `gpt4_ab202e7f`, `d6233ab6` |

净值: **+2 −4 = −2** → 0.930 → 0.910。

REGRESS 4 的家族: cardinality/numeric ×2 (`9ee3ecd6` 300vs100, `gpt4_194be4b3` 计数)、
numeric recall ×1 (`d3ab962e` 8miles)、subjective preference ×1 (`1c0ddc50`)。
多为 parked/high-risk 家族或 stochastic answer-path failures；**无 infra error**。

**修正前述错误归因**: 之前写的"不同 stratified 抽样的正常波动"与"零 regression"
都是错的。正确结论:

> Current-main clean baseline is **0.910 on the identical 100-qid sample**. It is
> **−2pt vs historical V6.1.1 0.930, with 2 fixes and 4 regressions**. The
> regressions are mostly parked/high-risk families or stochastic answer-path
> failures; no infra errors. **Record this as a real current-main delta, not
> sampling noise.** Do NOT open a fix automatically.

**遵守纪律**: 本次是 formal baseline refresh，不是 repair loop。−2pt 是真实 delta，
但不在本次开 fix。若要追，单独开 "0.910 delta audit"（先只读看 4 个 regress 是否同一
机制 / 是否 answer-path 抖动），不边跑边修。

## 6. 处理动作
1. ✅ clean/infra 拆分：clean 0.910，无需 infra-adjust。
2. ✅ fail 归因用 PX 工具（classify_preliminary）+ V6.1.1 逐题对照（§5）→ 真实 −2pt
   delta（FIX 2 / REGRESS 4 / BOTH FAIL 5），非抽样噪声。
3. ✅ 写本 baseline log + artifact 保留。
4. ⏸️ README：**未改**（0.910 < 历史 0.930，是否对外替换 headline 由产品口径决定）。
5. LoCoMo: 未跑，保持 historical-only。

## 7. 下一步（待用户决定）
- 若要对外更新 current-main claim → 改 README/RELEASE 把 0.910 (clean, 2026-06-04,
  deepseek-v3.2/gpt-4o-judge) 作为 current-main baseline 行（与 historical 0.930 并列标注）。
- 否则此 artifact 作为内部 current-main 基线留档即可。
