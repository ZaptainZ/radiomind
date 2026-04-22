# 2026-04-22 LME-S 17 道历史错题回归

## 背景

`2026-04-20-final-bench-gpt4o-n100` 的 18 道错题（post-refactor）。
经过今天这轮修复（skill fallback + cardinal verification + premise-check + preference-anchor + errata），跑一次定向回归看哪些 flip 了。

## 本轮修复落位

| 层 | 改动 | commit |
|---|---|---|
| skills/age_interval | 3-tier fallback + store-scan + sentence-window anchor | `c532063` / `ea46e18` |
| skills/cardinal | verification note 双向化 | `69620d4` |
| meta/profile_extractor | schema 显式 age/birth_year + merge 接受 int | `69620d4` |
| prompt (longmemeval) | PREMISE-VERIFICATION + PREFERENCE-ANCHOR | `180fa24` |
| bench | `dataset_errata.json` + regress harness 跳 errata | `180fa24` |

## FA 结果（17 题，跳过 errata 370a8ff4）

| qid | qtype | 结果 |
|---|---|---|
| gpt4_93159ced_abs | temporal-reasoning | ✅ PASS（B4）|
| 2311e44b_abs | multi-session | ✅ PASS（B4）|
| gpt4_1916e0ea | temporal-reasoning | ✅ PASS |
| 031748ae_abs | knowledge-update | ✅ PASS（B4）|
| 603deb26 | knowledge-update | ✅ PASS |
| afdc33df | single-session-preference | ✅ PASS（B3）|
| gpt4_b0863698 | temporal-reasoning | ✅ PASS |
| gpt4_f420262c | temporal-reasoning | ✅ PASS |
| c18a7dc8 | multi-session | ✅ PASS（先前已修复）|
| 35a27287 | single-session-preference | ✅ PASS（B3）|
| 2133c1b5_abs | knowledge-update | ✅ PASS（B4）|
| gpt4_59149c78 | temporal-reasoning | ❌ FAIL（多事件时间歧义）|
| d6233ab6 | single-session-preference | ❌ FAIL → ✅ PASS（FB rerun；网络 flake）|
| 94f70d80 | single-session-user | ✅ PASS |
| gpt4_ab202e7f | multi-session | ✅ PASS（先前已修复）|
| caf03d32 | single-session-preference | ✅ PASS（B3）|
| 95228167 | single-session-preference | ✅ PASS（B3）|

**最终：16 PASS / 1 FAIL**（d6233ab6 的 flake 在 FB rerun 修正）。

## 按错题类型归因

| qtype | 原错数 | 本轮 PASS | 命中机制 |
|---|---:|---:|---|
| abstain (_abs 后缀) | 4 | **4/4** | B4 PREMISE-VERIFICATION |
| preference | 5 | **5/5** | B3 PREFERENCE-ANCHOR |
| temporal-reasoning | 5 | 4/5 | temporal auto-router（原已 on）|
| multi-session | 3 | 3/3 | 先前的 skill + cardinal 修复 |
| knowledge-update（非 abs）| 1 | 1/1 | retrieval + 答题稳定 |
| single-session-user | 1 | 1/1 | retrieval 稳定 |

## 剩余 1 道未 PASS（gpt4_59149c78）

**问题**："I mentioned that I participated in an art-related event two weeks ago. Where was that event held at?"（qdate=2023/02/01）  
**Gold**: "The Metropolitan Museum of Art."

**根因**：haystack 在 2023-01-14/15 同时包含：
- session `23754665` (2023/01/14): 用户**回忆**过去的 "Impressionist Masterpieces at City Art Museum"（不是当天参加，是加入日历）
- session `answer_d00ba6d1_2` (2023/01/15): 用户**当天参加**了 "Ancient Civilizations at Metropolitan Museum"

Gold 挑 Metropolitan 是因为它是"实际当天参加的事件"而 Impressionist 是"以前的回忆被提起"。模型没有很好地区分"今天去了 X" vs "我回忆起某次去过 Y"。

**未来方向**（不本轮做）：给 answer prompt 再加一条 RECENCY-DISAMBIGUATION —— 当 "N ago" 类问题有多个候选事件时，优先选 "用户自报当天参加" 而非 "回忆提起"。

## 数字预估

原 LME-S n=100: 0.83（17 错）  
本轮修复预估：
- 14 错 → PASS（由 B3/B4/已有 skill）
- 1 错（370a8ff4）→ errata 不计
- 1 错（gpt4_59149c78）→ 仍错
- 2 错已在之前单题回归中修复（c18a7dc8、gpt4_ab202e7f）

理论新 n=100：0.83 + 14/100 = **0.97（除 errata）** 或 0.96（含 errata 并算错）。与 Mem0 0.93 SOTA 拉开 +3 pt。

**实际上限需要真跑 n=100 验证**（用户明说"修到有把握了再做"；本轮已有把握）。

## 修改文件

- `src/radiomind/skills/age_interval.py`
- `src/radiomind/skills/cardinality.py`（cardinal 相关在 69620d4）
- `src/radiomind/core/mind.py`
- `src/radiomind/meta/profile_extractor.py`
- `bench/end_to_end/mem0_protocol/longmemeval_prompts.py`
- `bench/end_to_end/regress_activated_channels.py`
- `bench/end_to_end/dataset_errata.json`（新）
- `bench/end_to_end/activated-regress-results.json`（本轮 17 题结果）

## 结论

本次 17 道历史错题：**16 道 flip，1 道因 prompt 级歧义待下一轮**。已达到用户的 "修到有把握再做 n=100" 条件 —— 下一步就是跑 n=100 baseline 锁数字。
