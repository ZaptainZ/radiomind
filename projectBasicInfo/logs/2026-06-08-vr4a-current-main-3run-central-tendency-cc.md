# VR-4a — current-main same-arch 3-run central tendency

> 作者: Claude Code (cc) ｜ 日期: 2026-06-08
> 目标: 建立 current-main 在同一 100 题上的真实中心（追 SOTA 的必要前置）。
> 范围: 测量,不改代码,不开 fix。同 qid set+order,fresh sandbox,同配置。

---

## 1. 三次 run（全 infra-clean）
同一 100 qid 同顺序（`--n 100` 固定 seed=20260416,已离线核对逐字复现 baseline set+order）,
deepseek-v3.2/dashscope answer + gpt-4o/openrouter judge,a2a-practice,reranker on,fresh sandbox。

| run | acc | 备注 |
|---|---|---|
| run1 `2026-06-04-baseline` | 0.91 | judge_errors=0 |
| run2 `2026-06-06-run2.judge-fixed` | 0.92 | 原始 raw 0.89 有 3 个 SSL judge-error;单独 rejudge 3 qid 后 clean 0.92（原始 raw 留档 `*.raw-with-judgeerrors.json`） |
| run3 `2026-06-06-run3` | 0.90 | judge_errors=0 |

**run2 infra 处理**: 3 个 judge_failed（SSL UNEXPECTED_EOF）用 `rejudge_single_qid.py` 逐个重判
（rejudge_errors.py 漏检——verdict_tail 只存末 120 字符,"[judge error" 前缀被截断,模式匹配不到;
此为该工具缺陷,本步未改它,改用 single_qid 精确重判）。3 个全判 PASS,judge_errors→0。

## 2. stability-report --same-arch 结果
**mean 0.91 · std 0.01 · min 0.90 · max 0.92 · median 0.91**（report `reports/vr4a-stability/`）。
- per-qid: stable-pass 86 · stable-fail 5 · unstable 9。
- floor（仅 stable-pass）= 0.86;ceiling（unstable 全解）= 0.95。

## 3. 按决策规则判定
- **mean 0.91,落在 "0.91–0.92" 档** → 架构中心还差一点,**未稳定到 0.93**。
- **max 0.92 < 0.93,三次无一摸到 0.93** → **V6.1.1 0.930 确认是历史 lucky 上沿,非 current 常态**
  （与 VR-3c cross-version envelope 一致: 0.93=tied max,median 0.92）。
- 9 个 unstable 各不同机制（temporal/multi-session/preference 混杂）,**无 ≥2 同机制稳定
  regression** → **不开 fix**。
- → 决策规则指向 **VR-4b answer self-consistency**（收窄 unstable 方差,把中心往上推）,
  不是 helper/retrieval 单题追分。

## 4. 5 个 stable-fail 的 n=3 caveat（重要,别误判）
3-run 标出的 5 个 0/3 stable-fail: `1c0ddc50` `d3ab962e` `gpt4_d6585ce8` `gpt4_ab202e7f` `d6233ab6`。
**n=3 太小,会把 unstable 误标 stable-fail**: 例如 `d3ab962e` 在 VR-2c answer-only 是 **5/5 PASS**,
这里却 0/3——只是三次恰好都落 unlucky。
- **真结构地板**（跨 VR-2c/VR-3c/VR-4a 都几乎不解出）: `gpt4_d6585ce8`(temporal-ordering)、
  `gpt4_ab202e7f`(cardinality "5 items")、`d6233ab6`(subjective preference) —— §5 已 PARK 三家族。
- `1c0ddc50`(subjective,VR-3c 5/9)、`d3ab962e`(VR-2c 5/5) 实为 unstable,非地板。
→ 教训: stable-fail 判定需 n≥5–9;n=3 的 stable-fail 必须与更大样本（VR-2c/3c）交叉确认。

## 5. 对 SOTA 目标的结论
- **current-main 真实中心 ≈ 0.91（std 0.01,很稳）。SOTA 0.93 是 +2pt,在本架构 envelope 上沿
  可达但非常态。** 架构没退化,但"稳定 SOTA"还差一口气,且这口气主要在 9 个 unstable qid 的
  方差里(answer-gen 主导,见 VR-2c),不在可定位的 bug。
- **不作弊的下一步 = VR-4b: answer self-consistency 评估**（固定 store 多采样取众数/多数,
  看能否把 unstable 的 modal 从 fail 翻成 pass、把中心从 0.91 推向 0.92–0.93）。这是"揭示并
  稳定真实水平",非提分作弊。
- 真正"架构提升"候选只剩 3 个 structural-floor（parked 家族,diminishing returns）。

## 6. 双口径维持
Mem0-compatible 单 run 仍是唯一对外 headline;本 same-arch 0.91±0.01 是内部 central tendency,
report 已标 `same-arch-stability`,**不进 README**（README 继续 historical 口径,current-main
claim 是否公开由产品决定）。

## 7. 进度 / 下一步
- [x] VR-4a: current-main 3-run mean 0.91±0.01;0.93 是 lucky 上沿非常态;无可修 regression。
- 建议 **VR-4b**: answer self-consistency 的 bench-only 评估（k-sample answer 取众数,固定 store
  优先以隔离效果;不改默认协议,作为可选项验证）。不跑大样本前先小集验证机制。
- 不开 fix / 不改 runtime / 不改 README。
