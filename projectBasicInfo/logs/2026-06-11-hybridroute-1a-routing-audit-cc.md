# HybridRoute-1a — 只读路由可行性审计 → 精度完美但收益不稳，PARK

> 作者: Claude Code (cc) ｜ 日期: 2026-06-11
> 前置: v4-pro n=100 判读后用户裁决（方案 2: 维持 v3.2 默认,不跑 v4-pro repeat,
> v4-pro 归档为"地板可解性证据"）+ 授权本审计。
> 范围: 只读。零 runtime 改动。oracle simulation 用现有 artifact;路由规则只看
> question text / 现有分类器,不看 qid/gold。
> 门槛（用户预设）: 模拟净收益 ≥ +1 qid 且 false positive 很少 → 才进入实现评估。

## 1. 审计四问

### Q1: v4-pro FIX 可由问题表面稳定识别吗 → ✅（且不需要新分类器）
现成已 ship 的 `ListOrderingSkill` trigger 正则（`skills/list_ordering.py`,qid-blind）
在**全数据集 500 题命中恰好 7 题**,与 B-1 时代识别的 ordering cohort
（trips/museums/sports/airlines/concerts/concerts2/events3）**逐题重合**,全部
temporal-reasoning 排序形态,零家族外命中。ingest-sensitive aggregation 按裁决不碰。

### Q2: REGRESS 排除 → ✅ 结构性排除
三个 v4-pro REGRESS（d682f1a2/b6025781/6ae235be）与全部 16 道 preference 题
均不命中规则。广义正则（R2: order of/sequence of/chronological/earliest to latest…）
与现成 trigger（R1）命中集相同。

### Q3: oracle simulation（n=100 artifact,v4 verdict 路由命中处替换 v3.2）
两条规则均只路由 1 题（gpt4_d6585ce8,样本内 ordering cohort 只有它）:
| 对照 run | base → hybrid | gains | losses |
|---|---|---|---|
| r1 (06-04) | 91 → 92 (+1) | gpt4_d6585ce8 | 无 |
| r2 (06-06) | 92 → 93 (+1) | 同 | 无 |
| r3 (06-06) | 90 → 91 (+1) | 同 | 无 |

**形式上门槛达标**（+1,FP=0）。

### Q4: 误判风险 → 样本内 0,全集 0 家族外泄漏。复制 preference 摩擦税的通道不存在。

## 2. 稳定性核验（due diligence,揭示 +1 不稳）
oracle 的 +1 完全押在 v4-pro 对 gpt4_d6585ce8 的 **n=1 观测**上。fresh 单题 sandbox
（internal=v3.2 ingest）同 store 对照:

| 模型 | 结果 |
|---|---|
| v4-pro | seed P + answer-only **PFP**（3/4;rep2 **空答案**——深度思考吃光 1500 max_tokens 的 v4-pro 特有形态,truncated_stub retry 已触发但两次皆空） |
| **v3.2** | **FPP（2/3 过！）** |

v3.2 在 n=100 语境 0/3、历史 0/9,在这个 fresh store 上却 2/3 →
**"ordering 地板"不是纯 answer-模型边界,是 ingest/store 构成依赖的联合随机事件**。
v4-pro 抬高通过率但非确定打穿;期望路由增益 = P(v4)−P(v3.2),按现有观测是
分数级（~+0.1~0.5 qid）且随 store 漂移,**不是稳定 +1**。

## 3. 结论: PARK（不进实现评估）
- 路由**精度**已证完美（现成 trigger,0 FP）——实现成本极低;
- 路由**收益**未证稳定——oracle 的 +1 是单观测传播,被同 store 双模型对照证伪为
  随机优势。期望值无法可靠抬高中心到 0.92。
- **重开条件**: (a) ordering cohort 级对照（7 题 × v4-pro vs v3.2 各 ≥3 跑,成本 ~数小时
  ×2 模型）显示 v4-pro 有稳定优势边际（如 ≥+0.5 通过率差）;且 (b) v4-pro 空答案形态
  先缓解（如 v4-pro 调用提高 max_tokens / thinking 预算控制）。两者都需用户立项。

## 4. 同时归档（用户裁决,2026-06-11）
- **北极星组合维持 deepseek-v3.2 + gpt-4o 不变**;v4-pro 不作为默认替换理由
  （headline 持平 + 成本/耗时不成立）。
- **不跑 v4-pro n=100 repeat**（除非已决定升级北极星组合——当前数据不支持）。
- v4-pro 数据归档定位: **"更强 answer/ingest 模型确实能打穿部分 v3.2 地板"的可解性证据**
  （ordering 概率性、b46e15ed ingest 缺口）,非产品路径。

## 5. Artifacts
`hr1a-seed-gpt4_d6585ce8.json` / `hr1a-ao-{v4pro,v32}-rep{1..3}.json`。
oracle sim 规则与数字全录于 §1（脚本为一次性分析,未入库）。

## 6. 不做 / 守住
不实现路由。不改 runtime。不把"地板可解性"写成"地板已解"。v4-pro 空答案形态
记录为已知问题,修复属 v4-pro 线（已 PARK）的重开前提之一。
