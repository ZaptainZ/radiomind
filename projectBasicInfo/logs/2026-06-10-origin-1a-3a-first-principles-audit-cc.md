# Origin-1a/3a — 原点审计：记忆层级 × 方法论 对照 SOTA 缺口（read-only）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-10
> 范围: 只读。零代码改动、零 LLM 调用（attention.analyze 纯 regex）、零 benchmark。
> 背景: 用户授权"回到原点"——检查 L1-L4 / trinity / attention 哪些机制有未用满的提升空间，
> 关联到 SOTA 线（deepseek-v3.2 + gpt-4o 不作弊追 0.93）。
> 用户两点前置约束: (1) trinity stance 由 LLM 按任务张力自选、可多方多层，不写死角色;
> (2) 做梦/HDC/LoRA 应在"注入记忆后的合适时机"用起来，bench 即模拟实际使用（A2A-practice 精神）。

---

## 1. Origin-1a: counting 簇 × attention 确定性审计

对 B-1 的 14 个 counting qid 跑 `attention.analyze`（确定性）+ 对照 same-arch 3-run
（run1 baseline / run2 judge-fixed / run3）的逐题 verdict 与 answer 形态：

| qid | wants | answer_shape | shape 经 hint 可达 | 3-run | fail 形态 |
|---|---|---|---|---|---|
| 9ee3ecd6 | count | number | ✗ | FFP | 选错档位（答 300 总量,gold 100 差额）×2 |
| gpt4_194be4b3 | count | number | ✗ | FPF | run1 截断残桩 / run3 多数 1 个（5 vs 4） |
| gpt4_f2262a51 | count | number | ✗ | PPF | run3 少数 1 个（2 vs 3） |
| d3ab962e | count | number | ✗ | **FFF** | 三跑全 abstain（**stable fail**,非 unstable） |
| c18a7dc8 | date | relative_offset | ✓ | PPF | run3 abstain |
| b46e15ed | date | relative_offset | ✓ | FPP | run1 abstain |
| bb7c3b45 / d851d5ba / 9aaed6a3 / 031748ae_abs / 6aeb4375 | count | — | ✗ | PPP | （稳过,多有 helper 兜底） |
| gpt4_d12ceb0e / gpt4_8279ba02 / 71017276 | detail/date | — | ✓ | PPP | — |

### 1.1 缺口 ①（shape 约束接线）——**作为杠杆被证伪**

接线缺口本身属实：`_task_description_for` 只对 wants ∈ (date/inference/detail) 构建
hint，`_ANSWER_SHAPE_GUIDANCE["number"/"amount"]` 对 count 路径不可达。**但** base
answer prompt（`mem0_protocol/longmemeval_prompts.py`）里早已有**严格更强**的数值纪律：

- **DELTA vs ABSOLUTE** 规则（"need to earn → target − current"，附完整算例）
- **NUMERIC AGGREGATION enumerate-then-sum**（强制 (label,value,date) 三元组枚举）
- counting 二次全扫描 + 动词限定词严格匹配 + 完成时态校验

9ee3ecd6 在 prompt 里有**现成同构算例**的情况下仍 2/3 跑答 300；gpt4_194be4b3 /
gpt4_f2262a51 在 enumerate-then-sum 强制下仍数错 ±1。→ **prompt 约束族对这些形态
已被实证打穿**（与历史 T1.3 "enumerate-then-sum 对 deepseek 数字能力没补上"、VR-2c/4b
结论三方一致）。原方案 Origin-1b（注入 shape 约束）**不立项**。

### 1.2 ⚠️ 诚实性边界发现（需用户裁决）

`longmemeval_prompts.py` 的 DELTA 规则算例用的是 **9ee3ecd6 的原题数字**
（"I have 200 points now" + "need 300 total" → 100, NOT 300）。措辞通用但数字来自
该 fail qid，按北极星硬定义（"不针对 benchmark 题目特调"）属**边界情况**（V6/V7 时代
遗留，早于当前纪律）。选项: (a) 把算例数字改成无关数字（如 50/120→70），可能丢掉
9ee3ecd6 仅有的 1/3 pass; (b) 保留并在文档注明。**裁决权在用户。**

### 1.3 真实残留缺口（确认）

1. **截断不重试**: `_answer_with_retry` 只接异常；200-OK 但被截断/strip 后残桩的
   answer（gpt4_194be4b3 run1 "You currently own"）直接放行。历史 v2 run 曾 4/100
   截断。确定性"截断检测 + 单次重试"与 C1/C2/C3 同族，窄面、bench-side、可回归覆盖。
2. **可观测缺口**: per_query 的 helper_hints 只覆盖 6 个 deterministic helper；
   atomic_section / cardinal_section 是否注入**无任何记录**（diagnose 也只记
   structured_skill_section）。→ S2（decomposer trinity 化）的前提（"没触发"还是
   "触发但产出错"）**从现有 artifact 无法判定**，需先补 bench-side 观测字段。
3. **d3ab962e 重新定性**: same-arch 3-run FFF（stable fail），但 VR-2c 固定 store
   5/5 PASS → 是 **ingest 方差决定窗口构成**的形态（codex 的 retrieval-attention 读法
   成立），非 answer 噪声。单题，不够 cohort，但它是 Origin-3（做梦修剪去冗余→窗口
   稳定）唯一的具体试验靶。

## 2. Origin-3a: 做梦 / HDC / LoRA 的 bench 路径审计

| 机制 | 实现状态 | bench 现状 | 挂载点 | 评估 |
|---|---|---|---|---|
| 做梦炼化 | 完整（`DreamRefinement`: prune 矛盾/冗余/衰减 + wander + journal；`mind.trigger_dream()`） | **从未调用** | `ingest_turns_raw` 完成后、答题前（="夜晚"） | 可试。收益假设: 合并冗余 FACT → top-k 窗口构成更稳（d3ab962e 靶）。风险: merge 毁掉 distinct events 伤 counting；侵蚀 preservative 优势。成本: 每 domain 若干 LLM 调用 ×100 |
| HDC 习惯 | HabitStore 在写；NL 相似度弱是已知问题 | **间接已激活**（chat 炼化 habit 镜像为 L2 PRINCIPLE，pyramid 可捞） | 已在 | 无新接线需求 |
| LoRA | 训练/部署链路通（env-gated） | 不可行（每 sandbox 需训练周期，bench 时间尺度不允许） | — | bench 侧 PARK（产品侧价值另论，LoRA must stay） |

**Origin-3b 草案**（待授权）: bench-only flag `--dream-after-ingest`（默认 off）；
2 qid 探针（d3ab962e + 1 个稳过 control）：ingest → store snapshot → trigger_dream →
diff（merge/prune 了什么）→ answer-only replay ×5 前后对照。不承诺分数，只验证
"模拟完整性"对窗口稳定性的影响。

## 3. 结论与建议次序

1. **开**: 截断重试（W3，窄、确定性、in-bounds）。
2. **裁决**: DELTA 算例数字去题化（§1.2，诚实性 vs 1/3 pass 风险）。
3. **开（前置）**: per_query 增记 atomic/cardinal section 注入与否（观测字段，零 runtime
   改动）→ 跑下一次 n=100 时自然积累 S2 判定证据。
4. **待授权**: Origin-3b 做梦探针（用户"模拟实际使用"方向的第一个可证伪实验）。
5. **不立项**: Origin-1b shape 约束注入（§1.1 证伪）；S2 trinity decompose 暂缓至
   #3 出证据（若开，stance 按用户约束由 LLM 自选张力，不写死"守护/探索/精简"）。

## 4. 不做 / 守住

本轮零代码改动。不重开已 PARK 方向（检索加权/ordering/preference）。不把任何
stability-adjusted 口径混入对外 headline。
