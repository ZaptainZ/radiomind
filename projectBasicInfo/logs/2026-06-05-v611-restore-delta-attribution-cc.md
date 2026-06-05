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

## 2b. Step 2 结果（4 qid × 5 current-main repeat）

| qid | passes/5 | 判定 |
|---|---|---|
| `9ee3ecd6` | **3/5** | 真随机摇摆（数值题 borderline） |
| `1c0ddc50` | **4/5** | 随机摇摆（主观偏好） |
| `gpt4_194be4b3` | **5/5 PASS** | baseline 截断 = 一次性 transient，**5/5 完整列出 4 instruments，从未复现** |
| `d3ab962e` | **5/5 PASS** | baseline abstain = 一次性 transient，**5/5 答 "8 miles"，从未复现** |

**两个 smoking-gun 嫌疑全部洗清**: `gpt4_194be4b3` 截断、`d3ab962e` abstain 都不可复现
→ 是单次 transient，**不是确定性 runner/max_tokens/gate bug，无需修**。

**judge 非确定性铁证**: `9ee3ecd6` rep1/2/3 答案**逐字相同**
（"You need to earn 100 more points."），gpt-4o judge 却返回 yes / yes / **no**。
即 n=100 的方差里**有一部分连 answer 都没变、纯粹是 judge 抖动**。

## 3. Step 3 — MOOT（无 stable regression 可 diff）
Step 3 仅对"仍稳定 FAIL"的 qid 做 prompt/evidence diff。4 个里 0 个稳定 FAIL → 跳过。

## 4. 最终归因结论

**−2pt（V6.1.1 0.930 → current-main 0.910，同题集）= run-to-run 随机性，不是代码 regression。**
三个随机源叠加:
1. answer-LLM 采样（gpt4_194be4b3/d3ab962e 的 transient、1c0ddc50 摇摆）
2. **judge-LLM 非确定**（9ee3ecd6 同答案被判 yes 和 no）
3. ingest 三体 refinement 的 LLM 随机性（每次重 ingest 的 L3/meta 都不同）

证据链:
- Step 1: runner answer-path 代码对这 4 qid 与 V6.1.1 等价（strip/gate/max_tokens 未变，
  新 helper 不 fire）→ 排除 runner answer-path regression。
- Step 2: 4 个里 2 个 baseline-fail 是 transient（5/5 翻 PASS），另 2 个是 borderline
  摇摆（3/5、4/5），均非稳定 regression。
- 这 4 个 swing qid 当前期望 ≈ (0.6+0.8+1.0+1.0)/4 = **0.85**；V6.1.1 在它们上拿了
  lucky 4/4，current baseline 拿了 unlucky 0/4 —— 单这 4 题就足以解释 −2pt。**架构未退化。**

**修复门槛: 不满足**（无 ≥2 同机制 stable regression，无 deterministic runner bug）→ **不开 fix。**

## 5. 对 SOTA 目标的真正杠杆（产品化方向，非本 log 执行）
既然 −2pt 是测量/采样噪声而非架构退化，追 SOTA 的正确动作是**降方差 + 多跑取统计**，
不是去 hardcode 这 4 题:
1. **judge 稳定化**（最干净的赢面）: judge temperature=0 或 3-judge 多数投票——
   9ee3ecd6 证明同一答案会被 judge 翻面，这是纯测量噪声，可消除。
2. **answer 稳定化**: 降 answer temperature / self-consistency 多采样取众数。
3. **报告口径**: current-main 用 n=100 ×3 的 mean±std 或 mode，而不是单次 run，
   避免再被 lucky/unlucky 单跑误导（V6.1.1 0.930 即单跑高尾）。
这三条都不作弊（不碰 gold/题特调），符合北极星定义，是下一条可选工作线。

## 6. 进度
- [x] Step 1 code-path diff audit —— 无确定性 runner regression。
- [x] Step 2 repeat ×5 —— 无 stable regression；2 transient + 2 stochastic；judge 非确定确证。
- [x] Step 3 —— moot（无 stable fail）。
- [x] 结论: −2pt = stochastic，架构未退化，不开 fix。下一步杠杆 = 降方差（§5）。
