# V611-Restore / Delta Attribution — 解释 0.930 → 0.910 的 −2pt

> 作者: Claude Code (cc) ｜ 日期: 2026-06-05
> 目标线: 不 park。回答"同一 100 qid 下 V6.1.1 0.930 → current-main 0.910 的 −2pt 是
> model stochastic 还是 current 引入了可定位 answer-path regression"。
> 产品前提: 见 `01_PROJECT_OVERVIEW.md` 北极星——deepseek-v3.2 + gpt-4o judge 不作弊追 SOTA。

---

## 0. 已确定事实
- 两次同一 100 qid、同顺序（脚本核对 same set + order）。
- 配置表面一致: deepseek-v3.2 / gpt-4o judge / dashscope / openrouter / a2a-practice / reranker on。
- current-main clean 0.910（judge_errors=0），V6.1.1 0.930。
- 净差 = FIX 2 − REGRESS 4 = −2。REGRESS: `9ee3ecd6` `1c0ddc50` `gpt4_194be4b3` `d3ab962e`。

## 1. Step 1 — 只读 code-path diff audit（runner / answer-prompt 层）

参照点: V6.1.1 outcome 提交 `4aa076c`（0.930 artifact 在此提交）。其后是整条
V8.2→V8.4 closure/helper 系列 + JAB + AnswerRetry + PX-1/PX-2。runner 由 818 → 1146 行。

**逐项对照（V6.1.1 → current）**:

| answer-path 元素 | V6.1.1 | current | 判定 |
|---|---|---|---|
| answer max_tokens | 1500 | 1500 | **相同** |
| `strip_thinking` | 有 | 有 | **逐字相同**（diff 为空） |
| `BidirectionalAbstainGate` (`salvage.py`) | 有 | 有 | **零改动**（`git diff 4aa076c HEAD -- salvage.py` 为空） |
| answer 调用包装 | 直接 `strip_thinking(llm_call(1500))` | `_answer_with_retry` | **成功路径等价**（仅多了网络异常外层重试，不在短答/abstain 上重试） |
| `get_meta_calibration` 注入 | 有 | 有 | runner 注入逻辑相同（内容由 src 生成，见下） |
| cardinal/temporal/open_domain/profile/preference/entity/atomic section | 有 | 有 | runner 组装逻辑相同 |
| **新增** role_guard / TESG / cashback / savings / person_age / list_ordering section | 无 | 有 | **4 个 regress qid 全部不 fire 这些**（hints≈空），故不污染这 4 题 |

**Step 1 结论**: 对"不 fire 新 helper 的 qid"而言，**runner answer-path 代码与 V6.1.1
功能等价**。4 个 regression **不是 runner answer-path 代码改坏**。剩余变量只剩两个，
都在 runner 之外:
1. **src/radiomind V8.x 内容漂移**: `mind.search` 检索顺序、`run_preference_context` /
   `run_temporal_precision` / `run_open_domain_specific` 的 section 内容、
   `get_meta_calibration` 的自画像文本——都随 V8.x ingest/skill 改动而变，进而改变
   注入 answer-prompt 的内容。
2. **未 pin 的 answer-LLM 采样**（含 ingest 阶段三体 refinement 的 LLM 随机性）。

→ 两者无法靠读代码分离，必须 Step 2 repeat。**没有发现确定性 runner regression 可直接修。**

### 单题初步形态（来自 baseline artifact，未重跑）
- `gpt4_194be4b3`: answer = "You currently own"（截断）。strip/max_tokens 均未变 →
  极可能是 verbose `<mem_thinking>` 吃掉 1500 budget 后 strip 留残桩（802-805 行注释
  记载过同类: 800→1500 是因为 4/100 曾被截断）。gold 是长列表，生成需大量 token。
  **形态 = max_tokens-vs-verbose-thinking 脆弱性，采样依赖**。
- `d3ab962e`: 8 miles → pure abstain。gate 代码未变 → 若是 gate 翻的，则因 src 侧
  memory/检索内容变了导致 gate 判 unsupported；也可能纯采样。
- `9ee3ecd6`: 100 → 300。数值选择（remaining vs total tier），无 helper，answer-path/采样。
- `1c0ddc50`: 偏好反向（推荐 user 想避开的 true-crime/self-improv）。preference_section
  内容（src 侧）漂移或采样。主观题，结构地板。

## 2. Step 2 — 4 qid targeted repeat（current-main，进行中）
不跑 n=100。对 4 qid 各跑 **5 次** current-main 全流程（含 ingest，因三体 refinement
也是随机源），判定每题是 stable FAIL（真 regression）还是 PASS/FAIL 摇摆（stochastic）。
重点看 `gpt4_194be4b3` 是否多次截断（→ runner/max_tokens 脆弱性）还是一次性 transient。

- 命令: `run_longmemeval_mem0.py --qids 9ee3ecd6,1c0ddc50,gpt4_194be4b3,d3ab962e`
  ×5，独立 sandbox/out，deepseek-v3.2/dashscope + gpt-4o/openrouter。
- 产出: 每 qid 的 5 次 pass/fail 向量 + answer 文本（看截断/abstain 复现率）。

判定矩阵:
- 多数仍 FAIL 且同形 → 真 current regression，进 Step 3 prompt/evidence diff。
- PASS/FAIL 摇摆 → stochastic，−2pt 含采样份额（V6.1.1 0.930 可能部分 lucky）。
- `gpt4_194be4b3` 多次截断 → runner/max_tokens 确定性脆弱（窄修候选）；仅一次 → transient。

## 3. 修复门槛（Step 2/3 证明机制后才开）
≥2 qid 同机制 **或** 1 个明确 deterministic runner bug；可复现；窄面；target-pack 不回归；
不靠 gold/qid hardcode。否则记录归因、不修。

## 4. 进度
- [x] Step 1 code-path diff audit（本 log §1）—— 无确定性 runner regression。
- [ ] Step 2 repeat ×5（运行中）。
- [ ] Step 3 stable-fail 的 prompt/evidence diff（视 Step 2 结果）。
