# S2 section-quality audit — 未命中 ≥2 同机制门槛 → benchmark 线正式收口

> 作者: Claude Code (cc) ｜ 日期: 2026-06-10
> 前置: Origin-1b 的 prompt_sections telemetry + 用户裁决（只采集不修;≥2 同机制才立项;
> 没有则 benchmark 侧正式收口,不再追 0.93;单题现象不开修复）。
> 范围: 14 个 counting 簇 qid 单轮采集（fresh sandbox,标准组合）+ 离线审计。零代码改动。

## 1. 采集
`--qids` 14 counting qids,deepseek-v3.2/dashscope + gpt-4o/openrouter,
artifact `bench/end_to_end/s2-counting-telemetry.json`。overall 11/14 = 0.786
（最难 cohort,符合预期）。

## 2. 审计表（atomic/cardinal = present/chars; 3run = 06-04/06/06 历史）

| qid | 本轮 | 3run | atomic | cardinal | ftype |
|---|---|---|---|---|---|
| 9ee3ecd6 | **F** | FFP | **Y/494** | n | concrete-wrong（又答 300） |
| c18a7dc8 | **F** | PPF | n | n | abstain-no-hint |
| b46e15ed | **F** | FPP | n | n | abstain-no-hint |
| gpt4_194be4b3 | P | FPF | n | **Y/2830** | pass |
| d851d5ba | P | PPP | n | **Y/3291** | pass |
| gpt4_f2262a51 | P | PPF | Y/495 | n | pass |
| d3ab962e | P | FFF | Y/367 | n | pass |
| 其余 7 题 | P | 稳 | 4×atomic / 3×无(date型) | n | pass |

触发面: atomic 7/14、cardinal 2/14;两者皆无的 5 题中 4 题 wants=date——decomposer
按设计不服务 date 路由,缺失是 by-design。**cardinal 并非死路径**: entity-class 缓存
命中时注入量大（2830/3291 chars）且两题本轮均 PASS。

## 3. 按预设标准判读
- **section-present-but-wrong = 1**（9ee3ecd6）: atomic 在场仍答 300。叠加事实——DELTA
  算例去题化后行为不变（之前 2/3 错,现仍错）——进一步坐实档位选择是 answer 端噪声
  （VR-2c 固定 store 1/5、VR-4b 不可聚合、Origin-1a prompt 族证伪、本轮 section 也救不了）。
  单题,不成簇。
- **section-missing-and-wrong = 2**（c18a7dc8/b46e15ed）但**与错误无因果**: 两题 wants=date,
  atomic/cardinal 本就不服务该路由;真实形态是时间区间 over-abstain 摇摆（PPF/FPP,
  V611-Restore 已证此类 abstain 多为一次性 transient）。把 decomposer 扩到 date 路由
  属新机制扩面,不是修接线缺口。
- → **"section 缺失或质量差且与错误相关"的同机制 cohort: n=1（最多）< 2。不立项。**

## 4. 结论
**S2 关闭;benchmark 侧（追 0.93）正式收口。** 至此在"deepseek-v3.2 + gpt-4o 公开 judge +
不 hardcode/不特调/不换模型"约束下,记忆侧全部杠杆审计完毕: helper 堆分（B-1 证伪）、
检索/聚合窄修（B-1.5 PARK）、self-consistency（VR-4b 证伪）、prompt 约束族（Origin-1a
证伪）、dream（Origin-3b 近中性）、section 质量（本审计 < 2 同机制）。
current-main 诚实中心 0.91 ± 0.01,上沿 0.92-0.93,即该组合的真实水平。

**校准两句旧表述**（用户指正,以此为准）:
- "answer 噪声不可修" → 准确说法: **在固定 deepseek-v3.2 + 公开协议 + 不特调的约束下,
  不能靠单题 helper / prompt 规则 / 重采样修**;
- "benchmark 边际收益清零" → 此前应为"除 S2 外清空",**本审计后才是清零**。

## 5. 后续（产品化 backlog,均需单独立项）
1. LoRA 部署链路量化损失（f16/更大 base/更多数据）
2. Dream 全域 redundancy pass
3. LoCoMo current-main refresh（仅当需对外重新声明 LoCoMo 时）
4. devtools / diagnose 报告打磨
另: 下次 formal n=100 refresh 时重新锚定 README 数字（hygiene 批改过 answer prompt）,
并自动积累全量 prompt_sections 交叉验证本审计。

## 6. 不做 / 守住
不修 9ee3ecd6（单题+已证噪声）。不扩 decomposer 到 date 路由。不把 0.786（14 题难簇
单轮）与任何 n=100 口径混用。
