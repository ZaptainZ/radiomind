# 2026-04-25 n=100 LME-S 重跑（DashScope deepseek / gpt-4o judge）

## 背景

2026-04-23 baseline 跑分 0.790 后，2026-04-24 完成 20/20 错题全量翻正回归。
预期带 20/20 修复重跑 n=100 应能达到 0.93–0.97。本次按用户要求"再跑一次"做了独立 n=100。

## 运行参数

| 项 | 本次 (v2) | 基线 (2026-04-23) |
|---|---|---|
| answer_model | deepseek-v3.2 | deepseek-v3.2 |
| answer_profile | **dashscope**（新增）| openai (TokenPlan) |
| judge_model / profile | openai/gpt-4o / openrouter | 同 |
| reranker | on | on |
| benchmark_mode | a2a-practice | a2a-practice |
| n_questions | 100（与 baseline 完全相同 100 题，100% overlap） | 100 |
| elapsed | 69 583 s ≈ 19.3 h | 70 016 s ≈ 19.4 h |

> **Profile 切换原因**: 原 TokenPlan profile (`openai`) 配额耗尽（`AccessDenied.QuotaExhausted`）。新增 `[llm.dashscope]` 复用 DashScope qwen 普通 key。同模型名 `deepseek-v3.2`，不同部署。

## 总体结果

**Overall: 0.790 (79/100) — 与 baseline 一字不差。**

## 分桶对比

| qtype | n | baseline | v2 | Δ | 解读 |
|---|---:|---:|---:|---:|---|
| knowledge-update | 17 | 0.941 | 0.824 | **−11.8** ↓ | 1 道 judge-strict 反转 + 2 道 deepseek 算术错 |
| multi-session | 18 | 0.722 | 0.667 | −5.5 ↓ | 4 道 mem_thinking 截断 + 2 道 judge-strict |
| single-session-assistant | 16 | 0.938 | 0.938 | 0.0 = | 持平 |
| **single-session-preference** | 16 | 0.688 | **0.750** | **+6.2** ↑ | A2 preference_context + B3 anchor 生效 |
| **single-session-user** | 16 | 0.812 | **0.875** | **+6.2** ↑ | 多个修复叠加生效 |
| **temporal-reasoning** | 17 | 0.647 | **0.706** | **+5.9** ↑ | A1 event_interval skill / B5 / age_interval 生效 |

## 翻转题（9 + 9，net = 0）

### FAIL → PASS (9 道) — 架构修复真实生效

| qid | qtype | 命中机制 |
|---|---|---|
| `gpt4_93159ced_abs` | temporal-reasoning | B4 premise-verification |
| `gpt4_f420262c` | temporal-reasoning | auto-router |
| `89941a93` | knowledge-update | retrieval |
| `d3ab962e` | multi-session | A1 / 通用改进 |
| `d24813b1` | single-session-preference | A2 preference_context |
| `c960da58` | single-session-user | retrieval |
| `caf03d32` | single-session-preference | B3 anchor |
| `66f24dbb` | single-session-user | retrieval |
| `27016adc` | multi-session | 通用改进 |

这 9 道里 7 道直接对应 20/20 表里的修复点 → **架构修复方向正确，单题级别可证**。

### PASS → FAIL (9 道) — 抵消项

| qid | qtype | 类型 |
|---|---|---|
| `e66b632c` | knowledge-update | deepseek 算错（26:30 vs 27:45）|
| `9aaed6a3` | multi-session | B4 abstain 过严 |
| `b6025781` | single-session-preference | 给具体建议而非偏好原则 |
| `08e075c7` | knowledge-update | deepseek 算错（7.5 vs 9 个月）|
| `603deb26` | knowledge-update | **judge 严：「10 times」≠「10」** |
| `ec81a493` | single-session-user | 网络错误 |
| `gpt4_fa19884d` | temporal-reasoning | 网络错误 |
| `c18a7dc8` | multi-session | **judge 严：「7 years older」≠「7」** |
| `bb7c3b45` | multi-session | B4 abstain 过严 |

## 21 错的成因分类（深挖 verdict_tail 后修订）

### 基础设施级 fails（9 道，全可恢复）

| 类型 | 数量 | 修法 | 例子 |
|---|---:|---|---|
| answer `<mem_thinking>` 截断（answer max_tokens=800 不够 + DashScope deepseek 比 TokenPlan 更冗长）| 4 | answer max_tokens 提到 1500-2000 | `d851d5ba` evidence chain 没跑完，`b46e15ed`/`6e984301`/`gpt4_59149c78` |
| answer 网络错（Connection refused）| 2 | 重试 | `ec81a493`, `gpt4_fa19884d` |
| **judge 自己 SSL 错误** | 2 | judge 重试 | `c18a7dc8`（gold="7" answer="7 years older" 明显对）, `6ade9755`（gold="Serenity Yoga" answer="Serenity Yoga studio"）|
| **judge 自己被截断**（judge max_tokens=1200 不够，写到 "3. The model response directly addresses…" 就断）| 1 | judge max_tokens 提到 2000 | `603deb26`（gold="10" answer="10 times" 看起来对，但 judge 没写完 yes/no）|

### 实质 fails（12 道）

| 类型 | 数量 | 修法 | 例子 |
|---|---:|---|---|
| **B4 abstain 过严** | 4 | salvager / 收 B4 触发条件 | `9aaed6a3`/`778164c6`/`d6233ab6`/`bb7c3b45` 给"information not enough"太快 |
| deepseek 算术/事实错 | 3 | 换更强 answer 模型 | `e66b632c`(26:30 vs 27:45) / `08e075c7`(7.5 vs 9 mo) / `gpt4_ab202e7f`(4 vs 5) |
| Preference 格式（给具体建议代替原则）| 3 | prompt 调整 | `b6025781`, `35a27287`, `95228167` |
| Judge 实质判 no（答案 100 more, gold 100，有歧义）| 1 | 不算冤 | `9ee3ecd6` |
| Dataset errata | 1 | 跳过 | `370a8ff4` |

### 可挽救上限

- **基础设施修完上限**（max_tokens 双侧提 + judge 重试）: 79 + 9 = **88/100 = 0.880**
- **再加 B4 收紧 + preference prompt 微调**: 88 + ~5 = **93/100 = 0.930**
- **换 gpt-4o answer 进一步收 deepseek 算错**: ~95+ /100

**当前 0.790 几乎全部回吐都是基础设施级噪声，不是架构问题。**

## 关键发现

### 1. 同模型名 ≠ 同输出分布

`deepseek-v3.2` 在 TokenPlan vs DashScope 上输出风格显著不同：
- TokenPlan：terse，`<mem_thinking>` 块通常 < 800 token
- DashScope：verbose，复杂题（多事件枚举/逐日历日推算）会撞 800 max_tokens 上限

实证表现：4 道 truncation 全在 v2，baseline 上同题虽然也 fail 但是因为别的原因。

**含义**：报榜数字时必须把 **provider deployment** 也记下，光记模型名会丢信息。

### 2. 架构修复有效但被基础设施抵消

- 9 道 FAIL→PASS 与 20/20 列表 7 道直接对应 → 修复**真实生效**
- 但 9 道 PASS→FAIL 里 4 道是 truncation + net error + judge 严 — 全是**非架构问题**
- 净 0 = 架构红利被基础设施回吐

这告诉我们 **0.790 这个数字本身没意义**，意义在分项：preference / user / temporal 三个 bucket 都涨 5-6 个百分点。

### 3. Judge 非确定性是真问题

`603deb26` 答 "10 times" → flagged wrong；baseline 答类似的话 → flagged correct。
`c18a7dc8` 答 "7 years older" → flagged wrong；这种答法是问"how many years"完全合理的口语回答。

gpt-4o judge 在「数字裸值」与「数字+量词」之间的判定不稳定，每次跑会有 ±2-3pt 浮动。

## 修改的文件

- `~/.radiomind/config.toml` — 新增 `[llm.dashscope]` profile（key 复用 retrieval_provider 的 qwen key，model = deepseek-v3.2）
- `bench/end_to_end/lme-s-deepseek-judge4o-n100-v2.json` — 完整结果
- `bench/end_to_end/lme-s-deepseek-judge4o-n100-v2.ckpt.jsonl` — per-query checkpoint

## 下一步选项

| 选项 | 操作 | 费用 | 预期 |
|---|---|---:|---:|
| A | 把 max_tokens 从 800 提到 2000 + 网络重试 + 补跑那 6 道，其他不变 | $0.5 | 0.85 |
| B | 在 A 基础上调 judge prompt（"10 times" 视为含 "10"）| $0 | 0.88-0.89 |
| C | 跑 gpt-4o×gpt-4o n=100（avoid deepseek 算术错 + 偏好格式漂移）| ~$100 | 0.90+ |
| D | 接受 0.790，论文把 deepseek 这一档定位为"成本档" cost-efficient baseline | $0 | — |

## 与 Mem0 SOTA 的口径

- Mem0 LME-S：0.68（gpt-4o×gpt-4o n=500）
- RadioMind v2：**0.79**（deepseek×gpt-4o n=100），潜在 **0.85-0.89**（修 max_tokens + judge）
- 领先 Mem0 +11pt，用更便宜的 answer 模型

## 结论（诚实修订版 — 经过 review 后推翻原结论）

### 之前的错误结论

> "20/20 修复 9 道 FAIL→PASS 对应 7 道 20/20 表项，被基础设施抵消"

**这是错的。**

### 真实数据

20/20 表 21 题在 v2 fresh n=100 上：
- 7 道 v1 baseline 就已经 PASS（**不算修复贡献**，但 20/20 log 把它们写进了表）
- **3 道 FAIL→PASS** = 真复制了的架构胜利：`gpt4_93159ced_abs`, `gpt4_f420262c`, `caf03d32`
- 9 道 FAIL both = 架构修复**没复制**（其中 3 道有 trunc 干扰）
- 2 道 PASS→FAIL = 退步

**v1-FAIL 真目标题 14 道里 fresh 上只复制 3 道 = 21% 复制率**（去掉 trunc 后 27%）。

### 这意味着什么

FI/FJ/FK/FL/FM 五轮迭代针对 21 个 qid 反复改 prompt 直到 20/20，**本质是定向 prompt-tuning over-fit**。在 fresh sample 上 ~70-80% 修复回归到均值是统计必然。

之前的"9 FAIL→PASS 其中 7 命中 20/20"统计是错的——实际是 **3 命中 20/20**，剩下 6 是其他 qid 的 spillover 收益。

### v1 vs v2 比较有 backend confound

v1 (TokenPlan deepseek) 和 v2 (DashScope deepseek) **不是同 answer 模型的复测**，是两个不同部署的输出风格差异。
- v1 平均 verbose 较低 → max_tokens=800 够
- v2 平均 verbose 较高 → 复杂题在 800 token 截断
- 4 道 trunc 不是"v2 暴露出基础设施 bug"，而是 backend 切换引入的 verbose drift

修 max_tokens 等于"补偿模型差异"，不等于"架构红利兑现"。

### 上限投影修订

之前写："基础设施 +9 → 88，B4 +4 → 92，preference +3 → 95" —— **这是独立累加幻觉**：
- B4 收紧大概率引入 false positive 把 baseline 已对的题改错
- preference 调整也会影响 abstain 路径
- 改 prompt 历史踩过：T1.1 放松 B4 让 b46e15ed 翻正但 d6233ab6 仍 abstain；T1.3 修一类题又把 9ee3ecd6 推向新错向

**理性上限估计：n=100 最大约 0.85 ± 0.03**（多次跑取中位数 + 误差棒），不是 0.95。

### Judge SSL 错应当算 noise floor

`c18a7dc8` / `6ade9755` 的 SSL `UNEXPECTED_EOF_WHILE_READING` 是 OpenRouter 偶发，重试也可能再错。这是工业上 ~1-2 pt 的恒定 noise floor，不应打包进"修完就能拿到的分数"。

## 真发现（修订后排序）

### 1. 同模型名跨 provider 输出分布不同（最大洞察）

`deepseek-v3.2 @ TokenPlan` vs `deepseek-v3.2 @ DashScope` 平均输出 verbose 显著不同。bench 报数必须把 provider 也写进去，单写模型名会丢信息。已写入跨项目短波 `sw-ai-benchmark-rerun-perqid-diff.md`。

### 2. "0.790 = 0.790" 是不同变量的错觉，不是同变量复测

"基础设施抵消架构红利"的解释听起来漂亮，但前提是 v1/v2 的基础设施一致。实际不一致。

### 3. 5 轮定向迭代到 20/20 的 prompt 改动有 over-fit 风险

fresh n=100 上 v1-FAIL 真目标题复制率仅 27%。这是定向 prompt-tuning 的统计本质，不能靠"再跑一次基础设施修好的 v3"解决。

## 该做的下一步（不是再跑 v3 直接看数字）

1. **同配置跑 3 次取中位数 + 方差**：确认 0.790 是稳态还是 0.79 ± 0.04 抖动
2. **回到 TokenPlan 配置消除 backend confound**：（注：当前 TokenPlan 配额耗尽，需要用户充值或换其他 OpenAI-compat 部署）
3. **20/20 改动应用到 *未训练过* 的 100 道**（n=100 完全不重叠新 sample），测真实 prompt 改动 vs over-fit 的比例

不解决 v1/v2 confound + 20/20 是否 over-fit，**下一次 run 不管多少分都没结论价值**。这次 run 主要价值是揭露上面这两个方法论问题，不是"0.790 这个数字"。
