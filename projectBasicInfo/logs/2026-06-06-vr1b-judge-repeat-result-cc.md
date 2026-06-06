# VR-1b — judge-only repeat 结果（judge 不是主力噪声源）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-06
> 范围: 只读测量。固定已有 artifact 的 (question, gold, answer),只重判 judge。
> 无 ingest、无 answer 生成、无 n=100、无 runtime 改动。harness: `vr1b_judge_repeat.py`。

---

## 1. 设置
- 8 qid × 10 judge-only repeats（gpt-4o / openrouter,temp=0,max_tokens=2000,
  复用 runner 的 `llm_call` / `JUDGE_PROMPT` / `_parse_judge_verdict`）。
- swing: `9ee3ecd6`(用 v611-rep1 那条触发翻面的逐字相同 answer "You need to earn
  100 more points.")、`1c0ddc50`、`gpt4_194be4b3`、`d3ab962e`（后三用 baseline answer）。
- 对照: stable-PASS `e9327a54`/`caf9ead2`（baseline+V6.1.1 都对）、
  stable-FAIL `b46e15ed`/`778164c6`（都错）。

## 2. 结果

| qid | role | seq (10) | yes_rate | label | ent |
|---|---|---|---|---|---|
| `9ee3ecd6` | swing | `YYYYYYYYYY` | 1.0 | STABLE | 0 |
| `1c0ddc50` | swing | `NNNNNNYNNN` | 0.1 | **FLIP** | 0.47 |
| `gpt4_194be4b3` | swing | `NNNNNNNNNN` | 0.0 | STABLE | 0 |
| `d3ab962e` | swing | `NNNNNNNNNN` | 0.0 | STABLE | 0 |
| `e9327a54` | ctrl-pass | `YYYYYYYYYY` | 1.0 | STABLE | 0 |
| `caf9ead2` | ctrl-pass | `YYYYYYYYYY` | 1.0 | STABLE | 0 |
| `b46e15ed` | ctrl-fail | `NNNNNNNNNN` | 0.0 | STABLE | 0 |
| `778164c6` | ctrl-fail | `NNNNNNNNNN` | 0.0 | STABLE | 0 |

**swing FLIP 1/4 · control FLIP 0/4 · judge_failed 0/80。**

## 3. 解读

### judge 非确定: 真实但稀有/低幅
- 唯一明显 flipper = `1c0ddc50`（主观偏好题,1/10 yes,ent 0.47）。
- `9ee3ecd6`（已知会翻面的那条逐字相同 answer）这轮 **10/10 yes**。结合 full-run
  里观察到的 1 次 no（v611-rep3），真实 judge flip rate ≈ 1/13 ≈ **8%,低频尾部**。
  按预设 gate（"仍 flip 才扩 20×"）它没 flip,故未扩。
- 4 个对照**全稳**（PASS 10/10、FAIL 10/10）→ judge 在非边界内容上零噪声。

### 关键: 0.910 的波动主力是 answer side,不是 judge
铁证（固定 answer 只重判时）:
- `gpt4_194be4b3`（baseline 截断答案）→ judge **稳定 0/10 NO**。它在 full-run 的
  **5/5 PASS** 来自**答案重新生成变好**,不是 judge 翻面。
- `d3ab962e`（baseline abstain 答案）→ judge **稳定 0/10 NO**。同理,5/5 PASS 来自
  答案侧 abstain→具体答案的变化。
- `1c0ddc50` full-run 4/5 PASS 也来自更好的答案样本（固定 baseline 失败答案只 1/10）。
→ swing qid 的"翻盘"几乎都发生在 **answer 生成端**（含 ingest 三体 refinement 影响
  检索/section 内容）,judge 端只贡献小幅低频噪声。

## 4. 结论与决策（按预设判定规则）
**judge 基本稳定（1/4 swing 低频 flip,控制 0/4）→ 0.910 波动主要来自 answer / ingest
side。**

- **不优先做 VR-1d N-judge majority。** judge 不是主力杠杆;N-judge 只能消掉估计
  ~1-3pt/run 的低频 judge 噪声(如 1c0ddc50 这类主观题),收益有限。它仍可作为**次要**
  稳定器保留为 harness 选项(默认 1,标注非同协议),但不是当前重点。
- **下一步应做 answer-side 稳定性测量(VR-2)**,而不是 majority judge。

## 5. 双口径(VR-1c)现状
- **Mem0-compatible score**(单 answer + 单 judge): 仍是唯一 headline/SOTA 口径。
- **Stability-adjusted score**: 若将来报告,应优先用 **answer-side n-run mean±std**
  (主力方差源),judge majority 是可选叠加项,且必须标注协议不同、不进 README headline。

## 6. 下一步建议(VR-2,待授权)
answer-side repeat / 稳定性:
- 对 swing qid(及若干 stable)做**固定 ingest、多次 answer 生成**的重复(隔离 answer
  采样),或**完整重 ingest+answer**的重复(含 refinement 随机)——区分 answer 采样 vs
  ingest-refinement 两个子源。
- 目的: 量化 answer-side 方差量级,判断"稳定 SOTA 分"该用 answer temperature 调低 /
  self-consistency / n-run 报告中的哪一种(均不作弊)。
- 仍不改 runtime、不写 README、不跑 full n=100(用小 qid 集)。

## 7. 进度
- [x] VR-1a audit(temp 已 0;非确定源 = OpenRouter 路由+模型内随机)。
- [x] VR-1b judge-only repeat: **judge 真实但稀有,非主力**;波动主力 = answer/ingest side。
- [ ] VR-1d N-judge: **降级为次要/可选**,不优先。
- [ ] VR-2 answer-side repeat（下一步主线）。
