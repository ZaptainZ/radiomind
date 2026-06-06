# VR-3b/3c — stability-report 实现 + 9-run 历史回放

> 作者: Claude Code (cc) ｜ 日期: 2026-06-06
> 范围: VR-3b 纯 artifact parser + devtools verb + 测试;VR-3c 用 9 个历史 same-qid
> artifact 回放。不跑 benchmark、不碰 src/radiomind、不改协议、不动 README。

---

## VR-3b 实现
- 新增 `bench/end_to_end/stability_report.py`（纯函数 + main）。
- devtools 加 `stability-report` verb:
  `--artifacts a.json b.json ... --out <dir> [--same-arch] [--current <path>]`。
- 校验: 所有 artifact **same qid set + same order + same length**,否则 `StabilityInputError`
  hard fail 并列差异。
- 输出 `stability.json` + `summary.md`: runs / mean·std·min·max·median /
  per-qid pass_rate+mode / unstable_qids(按 |pr−0.5| 排序) / by_qtype / family_summary /
  placement(高亮 run 的分位 + is_max/is_min + Δ)。
- `--same-arch` 仅改 `interpretation` 标签（`same-arch-stability` vs 默认
  `cross-version-envelope`）,**不验证架构**。caveat 写进 summary 顶部。
- 测试 `tests/test_stability_report.py`(13) + devtools dispatch(3) → regression pack
  `diagnostic:stability-report`。全绿,无 src diff。

## VR-3c 回放（9 个历史 same-qid+order artifact,全 deepseek-v3.2/gpt-4o judge）

**Envelope（cross-version,非同架构 std）**: mean **0.90**, std 0.037, min 0.82,
**max 0.93**, median **0.92**。

run 分布: 0.82(v4) / 0.86(v822a) / 0.89(v6.2.2) / 0.91(**current 06-04**) /
0.92(v5, v82-1, v822a-judge-fixed) / 0.93(**v6.1.1**, 2026-05-26)。

**关键结论:**
1. **current-main 0.910 落在历史区间内,在均值之上**（percentile 33.3, Δ vs mean +0.01,
   Δ vs max −0.02）→ **不是 regression**,是中等抽样。
2. **V6.1.1 0.930 = tied MAX**（与 05-26 并列最高）→ **确认 high-end / lucky run**。
   架构中心趋势 ≈ median **0.92**。
3. Per-qid（跨 9 run）: **stable-pass 68 · stable-fail 3 · unstable 29**。
   - floor（只 stable-pass）= **0.68**;ceiling（unstable 全解）= **0.97**。
4. **4 个"regression"qid 本来就 unstable**: 9ee3ecd6 6/9, gpt4_194be4b3 7/9,
   d3ab962e 7/9, 1c0ddc50 5/9 → 不是 current 改坏,是天生摇摆题,06-04 落 unlucky。
   印证 VR-2c（answer-gen 方差）在 cohort 层。
5. **3 个真结构地板（0/9,从未解出）**: `gpt4_d6585ce8`(temporal-ordering 演唱会顺序)、
   `gpt4_ab202e7f`(multi-session 计数 "5 items")、`d6233ab6`(subjective preference)
   —— 精确对应 DEV_WORKFLOW §5 已 PARK 的 ordering / cardinality / subjective-preference 家族。

## 对 SOTA 目标的整合结论
- **current-main 真实中心 ≈ 0.91–0.92,与 SOTA 0.93 仅一线之隔,且 0.93 在本架构的
  envelope 上沿内可达**（V6.1.1/05-26 已摸到）。架构没退化,也没远离 SOTA。
- **方差面 = 29 个 unstable qid**（central tendency 高低取决于每跑落多少 pass）;
  **真天花板 = 3 个 structural-floor qid**（parked 家族,可能是 subjective/ordering ceiling）。
- **追 SOTA 的正确动作（不作弊,按优先级）**:
  1. **same-arch k×repeat** current-main → 取真实 central tendency ± std（诚实 SOTA 数,
     当前 cohort 是 cross-version,std 偏大,尚不能当同架构 std）。
  2. **answer self-consistency**（现在测量已厘清,可正当评估）→ 收窄 29 unstable 的方差,
     把 central tendency 往上沿推。
  3. 3 个 structural-floor 才是"真需要架构改进"的候选,且多为 parked 家族(diminishing returns)。
- **不该做**: 用 helper/retrieval 单题追分（噪声盖过收益,且 4 个"regression"是噪声不是 bug）。

## 双口径(VR-1c/3a)维持
Mem0-compatible 单 run 仍是唯一对外 SOTA headline;本 envelope / 未来 stability std /
self-consistency 都是内部口径,summary 已显式标注 `cross-version-envelope`,不进 README。

## 进度 / 下一步建议
- [x] VR-3b stability-report 实现 + 测试。
- [x] VR-3c 9-run 回放: current 在区间内、V6.1.1 是上沿 lucky、29 unstable + 3 floor。
- 下一步（待授权,二选一或先后）:
  - **VR-4a**: current-main same-arch k×n=100 repeat（如 3×）→ 真 stability std + central
    tendency（用 `stability-report --same-arch`）。这是给出"可对外 claim 的 SOTA 数"的前提。
  - **VR-4b**: answer self-consistency 的 bench-only 评估（固定 store 多采样取众数,看能否
    在不作弊下收窄 unstable 方差）。
- 不在本步开 fix / 不跑新 benchmark / 不改 README。
