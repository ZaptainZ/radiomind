# VR-4b — answer self-consistency 评估结果（无收益,不推进）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-09
> 定位: bench-only 实验,评估 self-consistency 收益与副作用。不改默认协议、不改 runtime、
> 不跑 full n=100、结果只标 stability-adjusted。前置: VR-4a（中心 0.91±0.01）。

---

## 1. 实验
- 15 qid: 9 unstable（VR-4a）+ 3 stable-pass ctrl（7e974930/caf9ead2/e9327a54）+
  3 真 stable-fail ctrl（gpt4_d6585ce8 ordering / gpt4_ab202e7f cardinality / d6233ab6 subjective）。
- 固定 store（seed 1× full ingest）→ answer-only ×7（k=7,隔离 answer-gen 方差）。全 judge_failed=0。
- 离线聚合（无新协议）: baseline(seed 单次) / judge-majority(k 次 verdict 多数) /
  exact-mode(归一化答案众数 + 其 verdict)。脚本 `vr4b_self_consistency.py`。

## 2. 结果
| 口径 | acc(15 子集) | 净 flip |
|---|---|---|
| baseline single | 0.80 | — |
| **judge-majority** | **0.80** | **+1 −1 = 0** |
| exact-mode | 0.733 | （更差） |

by-role judge-majority delta: **unstable Δ0 · stable-pass Δ0 · stable-fail Δ0**（全零）。
- gain: `35a27287`（pr 0.857 → majority 修成 P）。
- loss: `9ee3ecd6`（pr 0.429 → majority 判 F,baseline 恰好 P → 翻成 F）。

**对照成功标准（unstable 净改善 ≥2）: 未达到（实际 0）→ self-consistency 无收益,不推进。**

## 3. 机制解释（为什么无效,且这是正确结论）
- **majority/self-consistency 不是"提分",是把每题收敛到它的真实期望值。** unstable qid 的
  pass_rate 分布在 0.43–1.0;majority 把 >0.5 的修成 P、<0.5 的修成 F——`9ee3ecd6` 真实期望
  是 fail（pr 0.43,VR-2c 早证众数 fail）,majority 诚实地把它从 lucky-P 翻成 F。修好的与
  拖垮的相抵 → 净 0。
- **exact-mode 更差（0.733)**: 答案文本高度分散（多数 qid distinct answers 5–7/7),
  众数答案样本太小、不稳,反而引入噪声。
- stable-pass 全 1.0（majority 不动）;stable-fail 真地板 majority 也救不了（gpt4_d6585ce8
  0/7,d6233ab6 0.143）—— 符合预期,controls 未被伤害也未被幻觉拉高。

## 4. 核心结论（对 SOTA 目标）
- **self-consistency 让分数更接近真实中心(~0.91 全集),而非超过它。** 它收窄方差,但
  current-main 的真实中心就是 0.91;**0.93 本就是 above-expectation 的 lucky 上沿,
  任何诚实的方差收窄手段都不会把中心推到 0.93。**
- → **追 SOTA 0.93 不能靠 self-consistency/取众数**（那只会把 lucky run 拉回中心,甚至略降,
  因为它移除了 favorable 的尾部抽样）。
- **真正剩下的、不作弊的提升路径只有"架构层面把 unstable qid 的真实期望从 ~0.6–0.85 提到
  ~0.9+"**,即改善这些 qid 的检索/记忆质量本身——但 VR-2c 已证主噪声是 answer-gen 对同一
  检索的表述不稳,不是检索缺失;且 9 个 unstable 各不同机制,无 cohort。
- **诚实口径结论: current-main = 0.91±0.01（same-arch）。这是真实 SOTA-adjacent 水平,
  但"稳定 0.93"在当前架构 + deepseek-v3.2 answer 噪声下不是常态,且不能靠测量技巧达成。**

## 5. 决策
- **不实现 `--answer-repeats/--answer-aggregation` bench flag**（VR-4b 失败,净 0,无收益)。
- 不开 fix。不改 README（继续 historical;current-main 0.91 是内部 stability-adjusted 数）。
- self-consistency 作为"降方差揭示真实水平"是有效的（9ee3ecd6 被诚实翻 F 即证),但作为
  "追 SOTA 提分"手段**证伪**。

## 6. VR 全线收束
VR-1（judge 非主力）→ VR-2（answer-gen 是主方差）→ VR-3（current 0.91 在历史区间内,
0.93 是 lucky 上沿）→ VR-4a（same-arch 中心 0.91±0.01 确认）→ VR-4b（self-consistency
不能把中心推到 0.93,证伪）。
**最终判断: 架构未退化,真实中心 0.91,距 SOTA 0.93 的 2pt 是 answer-model 噪声带 + 少量
parked 结构地板,非可定位 bug、非测量技巧可补。要真正稳定 ≥0.92,需架构层面提升 unstable
qid 的记忆/检索质量(需新 cohort 证据),不在当前 read-only/measurement 线内。**

## 7. 下一步（待用户定方向,VR 线测量已尽）
- 选项 A: 接受 0.91 为诚实 current-main,更新对外口径（README 标 current-main 0.91 same-arch
  + historical 0.93,需产品决定）。
- 选项 B: 转入架构提升线（针对 unstable qid 的检索/记忆质量,需先找 ≥2 同机制 cohort,
  按 DEV_WORKFLOW §3 门槛）——这才是唯一不作弊把中心推过 0.92 的路径,但需新证据立项。
- 不建议: 继续 blind repeat / self-consistency / 单题 helper 追分。
