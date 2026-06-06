# VR-2c — answer-path vs ingest 方差拆分结果

> 作者: Claude Code (cc) ｜ 日期: 2026-06-06
> 用 VR-2b 的 answer-only 模式隔离方差源。范围: 只读分析,不改 runtime,不开 fix。
> 样本: 6 qid（4 swing + 1 pass ctrl + 1 fail ctrl）。seed 1× → answer-only 5× → fresh 3×。

---

## 1. Pass matrix

| qid | seed | answer-only (固定 store) ×5 | fresh-full ×3 |
|---|---|---|---|
| `9ee3ecd6` | P | F F P F F **(1/5)** | F P P (2/3) |
| `1c0ddc50` | P | P P P F P (4/5) | P P F (2/3) |
| `gpt4_194be4b3` | P | P P P P P (5/5) | 3/3 |
| `d3ab962e` | P | P P P P P (5/5) | 3/3 |
| `e9327a54` (ctrl-pass) | P | 5/5 | 3/3 |
| `b46e15ed` (ctrl) | P | 5/5 | P P F (2/3) |

## 2. 结论: **answer-generation 是方差主因**

判定规则: 固定 store 也大波动 → answer generation 主因;固定稳但 fresh 波动 → ingest 主因。

- **固定 store（answer-only）仍大幅摇摆**: `9ee3ecd6` **1/5**, `1c0ddc50` 4/5。
  store/检索完全相同,answer LLM 每次在 4 种答案间跳（"300 points" 错 / "100 more to
  reach 300" judge 判错 / "100 more points" 对）→ **纯 answer-generation 方差**。
- **answer 早已 temp=0**（`llm_call` 对所有调用 temp=0.0）却仍 1/5 摇摆 →
  **deepseek-v3.2/DashScope 在 temp=0 下高度非确定,是最大噪声源**（比 gpt-4o judge 还不稳,
  对照 VR-1b judge 多为 stable）。
- **ingest/refinement 次要但存在**: `b46e15ed` 固定 store 5/5,fresh 有 1 次 F →
  不同 ingest（三体 refinement 随机）会改变结果,但幅度小于 answer-gen。
- **judge 最小**（VR-1b 已证）。

**方差层级: answer-LLM 生成 ≫ ingest/refinement > judge。**

## 3. answer-only 答案聚类（固定 store,变化纯来自 answer 生成）
- `9ee3ecd6`: 4 种不同答案前缀。模型对"还需 100"vs"共需 300"理解不稳 → 这是 answer 端
  对同一检索的**理解/表述不稳定**,且**众数偏 FAIL**（1/5 pass）→ 架构在这题真实水平
  ≈ 错,V6.1.1 的 pass 是 lucky。
- `1c0ddc50`: 4 种表述,众数 PASS（4/5）,主观题。
- 其余 4 题: 表述有 2-4 种但语义稳定正确（5/5）。

## 4. 对 SOTA 目标的结论（这是整条 VR 线的 payoff）

**单次 run 的 0.910 vs 0.930 不是可靠 SOTA 信号——方差主带来自 answer 模型本身（temp=0
仍非确定),±2pt 量级。** 追最后 2pt 去改 helper/retrieval 是错的方向（噪声就盖过 2pt）。

**不作弊的稳定化路径（按优先级,均不碰 gold/题）:**
1. **n-run 报告（mean±std / mode）**——零架构改动的测量诚实化。current-main 真实水平应
   报 n=100 ×k 的均值±方差,而非单跑。**最优先,最该先做。**
2. **answer self-consistency**（固定 store 多采样取众数/多数）——降 answer-gen 噪声的主手段。
   注意: 它会把 lucky-pass（如 9ee3ecd6）还原成 stable-fail,即**揭示真实水平而非提分**,
   符合北极星"测稳不作弊"。
3. **探查 DashScope `seed` 支持**（best-effort 确定性,VR-1a 记当前未传 seed）——次选。
4. judge N-majority（VR-1d）: **最低优先**,judge 非主力。

**temp 调低不可用**: answer 已 temp=0。

## 5. 边界 / 注意
- answer self-consistency 若实现,是 **answer-path 改动**——但属"采样策略"非"prompt/打分
  作弊",且应作为 bench/可选项先验证,再决定是否进默认。需单独 scope（VR-3）。
- 双口径不变: Mem0-compatible 单 answer+单 judge 仍是唯一对外 SOTA headline;
  self-consistency / n-run 是 stability-adjusted 内部口径,标注协议不同,不进 README headline。

## 6. 进度 / 下一步建议
- [x] VR-2c: answer-generation 是方差主因（固定 store 仍摇摆,temp 已 0）。
- 建议 **VR-3**: 先做"n-run 报告"口径（小样本验证 mean±std 能稳定区分架构水平),
  再评估 answer self-consistency（bench 可选,验证能否在不作弊下收窄方差band)。
- 不在本步开任何 fix / 不改 runtime / 不写 README。
