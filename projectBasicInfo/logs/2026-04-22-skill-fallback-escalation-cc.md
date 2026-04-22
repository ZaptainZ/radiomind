# 2026-04-22 skill fallback escalation

## 背景

继上一轮 "activate architectural channels" (e98f69f) 之后，跑一个聚焦 3 道 LME-S 历史失败题的回归验证（`c18a7dc8` age-interval, `370a8ff4` chain-reasoning, `gpt4_ab202e7f` kitchen 计数）。目的：确认新加的 age_interval / chain_reasoning / list_ordering skill 在端到端路径下是否按预期接管，并把 skill 的 fallback 链条补完整。

## 目标

1. 验证 skill 链在真实 LongMemEval-S 数据上的触发行为。
2. 补齐 age_interval skill 的 fallback：token match → trinity 语义匹配 → 全 store 扫 current age 自介。
3. Skill context 下 thread 必要的 `domain` / `user_id`，让 store-scan 能按域限定。

## 实施

### age_interval: 三层 fallback

`src/radiomind/skills/age_interval.py`
- `_find_event_via_trinity`: 当词面匹配（"graduated from college" ≠ "completed Bachelor's"）失败时，用 trinity debate 做语义对齐，同时顺便抽 `age_at_event`。
- `_scan_for_current_age` + `_find_current_age_in_memories`: 提取 retrieved 里的自我介绍（"I'm 32" / "as a 32-year-old X"），排除过去事件的年龄（"at the age of 25 I graduated"）。
- `_find_current_age_in_store`: 当 retrieval 漏掉自介 turn（典型场景：用户自介"32-year-old Digital Marketing Specialist"与"graduation"查询零 token overlap），直接扫 L0 FACT 层全量 entries（cap 500）。

三层优先级：profile (`who.age` / `birth_year`) → retrieved self-ID → store-scan self-ID。

### context threading

`src/radiomind/core/mind.py`
- `answer_hint` / `run_temporal_precision` / `run_open_domain_specific` 现在接受 `domain` + `user_id`，传入 skill context，让 store-scan fallback 能按域限定。

两条 bench harness (`run_locomo_mem0.py` / `run_longmemeval_mem0.py`) 同步把 `domain` 参数下传。

### 回归脚本

`bench/end_to_end/regress_activated_channels.py`（新）—— 通过 `REGRESS_QIDS` 环境变量筛选指定 qid，跑 ingest + answer_hint + run_temporal_precision + run_open_domain_specific 的端到端流程，结果写到 `activated-regress-results.json`（sections bitmap + prefix 注入文本 + 截断 answer，便于诊断 skill 是否被正确触发）。

## 测试结果

3 题回归（F6）：

| qid | type | result | 真正根因 |
|---|---|---|---|
| c18a7dc8 | age=7 | FAIL | profile_extractor 没抽到 "32-year-old" 自介；retrieval 也召不回（零 token overlap）。skill 的 store-scan fallback 应当能触发但本次未生效，说明 domain 参数传递链条仍有漏点。 |
| 370a8ff4 | weeks=15 | FAIL | temporal anchor extractor 把某次跑步错标为"第 10 次"（2023-04-10 vs 实际 ~2023-05-04）。ingest 层的 anchor 抽取精度问题。 |
| gpt4_ab202e7f | kitchen=5 | FAIL | 上一轮 F3 过，本轮不过。cardinal 抽到但最终答案漂移。LLM 随机性或 verification-note 的 prompt 不够锚。 |

单元测试全通过：`test_mind / test_refinement / test_numeric_aggregator` 32/32。

## 结论

**Skill 层工作正常** —— trinity escalation 能接管、chain_reasoning 能 decompose+sub+compose、cardinal 能发 verification note。但三题失败的根因都在 skill 之下的 ingest 管道（profile_extractor 漏抽、temporal anchor 误标、LLM 生成不稳定）。

剩余 gap 属于 ingest-layer 的工作：
1. profile_extractor 需要主动识别 self-ID 句式（"as a 32-year-old X"）。
2. temporal anchor extractor 的 ordinal 推理（"第 N 次 X"）需要端到端一致性校验。
3. cardinal 答案稳定性需要 prompt 再锚或引入一致性投票。

这些是下一层工作。本次架构改动（skill 三层 fallback + domain threading + 回归脚本）先固化。

## 修改文件

- `src/radiomind/skills/age_interval.py`（新）
- `src/radiomind/skills/chain_reasoning.py`（新）
- `src/radiomind/skills/list_ordering.py`（新）
- `src/radiomind/skills/registry.py`
- `src/radiomind/core/mind.py`（answer_hint 新签名 + 向后兼容 wrapper）
- `src/radiomind/meta/profile_extractor.py`
- `bench/end_to_end/run_locomo_mem0.py`
- `bench/end_to_end/run_longmemeval_mem0.py`
- `bench/end_to_end/regress_activated_channels.py`（新）
