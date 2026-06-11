# deepseek-v4-pro 线（开）— answer-only 归因 + internal-split flag + n=100 启动

> 作者: Claude Code (cc) ｜ 日期: 2026-06-10
> 背景: 用户决定尝试 deepseek-v4-pro（DashScope,1.6T MoE 深度思考,¥12/24 per M）。
> 口径（two-score 纪律延伸）: v4-pro 结果是**独立新线**（`deepseek-v4-pro + gpt-4o`）,
> 永不与 v3.2 的 0.91±0.01 混写。公开换组合按新组合声明不属作弊（硬定义禁的是
> 换强模型刷旧组合的分）;是否升级北极星组合 = 跑完后的用户产品决策。

## 1. 冒烟 + full-stack 速度问题
- 冒烟: DashScope OpenAI 兼容端点非流式正常,默认不开 thinking,纯 content,1.6s。
- **full-stack v4-pro 不可行**: ingest 内部 LLM（KG/三体/decomposer,每题数百调用）换成
  深度思考模型后 ~2.5h/题（v3.2 的 ~12 倍）→ n=100 需 ~10 天。已杀掉自动滚入 n=100 的
  驱动（checkpoint 无损）;14 题 full-stack 探针单独续跑作为 ingest 侧参考数据。

## 2. Answer-only 归因（决定性证据,固定 v3.2 store ×3 replay,VR-2b 工具）
S2 sandbox（v3.2-ingest,v3.2 基线 11/14）上只换 answer 模型:

| 项 | 结果 |
|---|---|
| v4-pro ×3 | **12/12/11**（v3.2 单跑 11） |
| c18a7dc8（时间 over-abstain） | **FFF→PPP 稳定翻正** |
| 9ee3ecd6（答 300 的档位混淆） | **数值层面解决**: 3/3 答 "100 more points"（gold=100）。判 F 是 **judge rubric 脆性**——v4-pro 答案更完整（同时报 200 现有/300 总需/100 差额）,judge 把 gold "100" 读作总需求,认为 "300 required" 与之矛盾。v3.2 历史过这题靠简短答案不提 300。**不改 judge 协议,分照算,归因记清。** |
| b46e15ed | 仍 FFF——该 store 的 ingest 没把 consecutive-days 证据送进窗口（v3.2 同 store 也挂）,非 answer 端问题 |
| gpt4_194be4b3 | PPF,残留 1/3 计数抖动（rep3 又数 5） |

**结论: v4-pro 实质性压住 answer 噪声族**（delta 算术稳定、时间 abstain 翻正）;
若不计 judge 脆性,语义正确率 13/13/12。

## 3. internal-split flag（bench-only,默认行为不变）
`--internal-model/--internal-profile`: ingest 管线用快模型,仅 answer 用重模型。
默认 None → 解析为 answer 模型（byte-identical 旧行为）。artifact 顶层新增
`internal_model/internal_profile` 字段保证可归因。`tests/test_internal_model_flag.py`
（4）+ pack `harness:internal-model-flag` → **25 类全绿**。

## 4. 进行中
- **n=100 split run**（answer=v4-pro / internal=v3.2,同 seed 20260416 同题集同序,
  可与 v3.2 三跑做逐题 flip）→ `lme-s-n100-2026-06-10-v4pro-answer.json`,预计 ~20h。
- 14 题 full-stack v4-pro 探针续跑（~27h）→ `v4pro-counting-probe.json`,用于 ingest 侧
  对照（如 b46e15ed 在 v4-pro ingest 的 store 里是否翻正）。
- 额度: 全程零配额/计费错误;免费额度耗尽自动转计费（控制台开关已是该配置）。

## 5. 待跑完后的判读问题
1. n=100 split vs v3.2 中心 0.91±0.01: 提升多少、9 个 unstable qid 的 flip 构成;
2. judge 脆性面有多大（v4-pro 的完整式答案风格 vs 简短 gold 的摩擦是否系统性）;
3. full-stack ingest 是否额外贡献（14 题对照）;
4. 成本/延迟 vs 收益 → 是否把北极星组合升级为 v4-pro（用户决策）。

## 6. 不做 / 守住
不改 judge prompt/协议（松判=作弊）。不把 v4-pro 任何数字写进 v3.2 口径。单跑 n=100
不下中心结论（需 repeat 才能 claim 中心,先看单跑量级）。

## 7. Full-stack 14 题探针结果（2026-06-11 补）
夜间 OpenRouter SSL 故障窗口造成大量 judge_failed（默认计 FAIL）;用修复后的
`rejudge_errors.py`（judge_failed 布尔选择,fa181fb）补判 4 条,3 条翻 PASS——工具债
修复当天就兑现了价值。**judge-fixed 后: 12/14 = 0.857**（v3.2 同簇 11/14）。

| qid | full-stack v4-pro vs v3.2 | 定性 |
|---|---|---|
| c18a7dc8 | F→P | answer 侧（与 AO 一致） |
| **b46e15ed** | **F→P** | **ingest 侧贡献首个实证**: v3.2 store 上 AO 也救不动（FFF）,v4-pro ingest 把 consecutive-days 证据送进了窗口（n=1） |
| 9ee3ecd6 | F→F | 仍是 judge rubric 脆性（数值又对: "100 more points… total of 300"） |
| 71017276 | **P→F 回归** | **answer 端虚假缺席**: 答 "no memories available",但 store 实有 8 条 aunt/chandelier 记忆、重放检索排名 1-5——不是 ingest 丢数据（lme_9 614 条,该 domain 最大）。n=1,不立项 |

结论维持: full-stack 的 ingest 侧有真实但混合的影响（b46e15ed 翻正 vs 71017276 引入
新形态的 false-absence）,且 12 倍耗时不可产品化。主线仍是 n=100 split。
另: 探针 sandbox 缺 lme_0-2（首次驱动被杀后 resume 跳过已完成 3 题、wipe 重建只
ingest 剩余 domain）——已完成题的 verdict 不受影响,但该 sandbox 不能用于这 3 题的
post-hoc 检索分析。
