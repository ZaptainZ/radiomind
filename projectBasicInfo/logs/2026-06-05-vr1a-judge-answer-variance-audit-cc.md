# VR-1a — Judge/Answer Variance Audit（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-05
> 目标: **不是把分做高,是把同一架构的真实水平测稳**,避免单次 lucky/unlucky 决定是否 SOTA。
> 范围: 只读 audit + 设计 VR-1b/1c。不改代码、不跑 ingest、不跑 n=100。
> 前置: V611-Restore 证明 −2pt = stochastic（含 judge 非确定）。

---

## 1. 五个 audit 问题的答案（读 `run_longmemeval_mem0.py`）

### Q1. judge 请求是否始终 temperature=0？
**是,而且 answer 也是。** `llm_call`（line 70-75）payload 写死
`"temperature": 0.0`,answer 与 judge 共用这一个函数。
→ **"加 temp=0 就能修" 是错的——温度早就是 0。** CC 此前的提法作废。

### Q2. OpenRouter/gpt-4o 是否仍非确定？
**是。** 两层原因:
- temp=0 对 GPT-4o 级模型**不保证 bit 确定**（MoE 路由 + 批处理 + 推理栈非确定）。
- judge profile = `openrouter`,model = `openai/gpt-4o`。OpenRouter 是路由器,
  **每次请求可能落到不同 upstream provider（OpenAI/Azure…）**,无 provider pin → backend 抖动。
- payload **无 `seed`、无 `top_p`、无 `provider` 字段**（grep 确认:runner 里除
  `temperature` 外无任何采样/确定性参数）。
- **实证**（不靠理论）: V611-Restore 已观察到 `9ee3ecd6` 三次 answer 逐字相同,
  judge 返回 yes/yes/no,且三次 verdict_tail 推理文本不同 → 是 judge 模型输出本身在变。

### Q3. retry 是否会换 backend/path？
- `llm_call` 内层 retry（3×）: 仅在 **异常**（429/5xx/SSL/网络）时重试,**同 URL 同 payload**,
  不换 model/profile。
- judge 外层 retry（line 906-920，3×）: 同样仅在 **Exception** 时重试,成功即 `break`,
  **不对成功的 judge 复投**。
→ retry 本身**不额外引入 verdict 方差**（成功路径单发）。但每次成功的 judge 调用经
  OpenRouter 仍可能命中不同 upstream——非确定性是**单次成功调用**固有,不是 retry 造成。

### Q4. 同一 (q, gold, answer) 多次 judge 的翻面率？
**未知 → VR-1b 测量。** 目前只有 1 个点证据（9ee3ecd6 在 5 次 full-run 里 yes/yes/no）。

### Q5. answer 端 vs judge 端各贡献多少方差？
**未量化。** V611-Restore 的 full-run repeat 把三源（answer 采样 + ingest refinement +
judge）混在一起。VR-1b 用 **固定 answer 只重 judge** 来隔离 judge 份额;与 full-run swing
对比即可推断 answer 份额。

## 2. 可控杠杆清单（VR-1d 备选,本步不实现）
| 杠杆 | 机制 | 代价/限制 |
|---|---|---|
| `seed` 参数 | OpenAI/OpenRouter best-effort 确定 + system_fingerprint | 仅 best-effort;gpt-4o 经 OpenRouter 可能忽略 |
| OpenRouter `provider` pin | `{"provider":{"order":["OpenAI"],"allow_fallbacks":false}}` 锁单 upstream | 减 backend 抖动,不消模型内随机 |
| openai_direct profile | 绕开 OpenRouter 路由 | **当前无 api_key**（config 里 openai_direct key 缺失） |
| **N-judge majority** | 同 answer 判 N 次取多数 | 最稳健,与 backend 是否确定无关;**改协议,需标注**（VR-1d） |

## 3. VR-1b 设计（judge-only repeat,待执行）
**不重跑 ingest/answer。** 直接复用已有 artifact 里的固定 `(question, gold, answer)`,
import 复用 runner 的 `llm_call` / `JUDGE_PROMPT` / `_parse_judge_verdict`,只重判。

- 目标三元组（answer 取自 `lme-s-n100-2026-06-04-baseline.json` 或 `v611-rep*.json`）:
  - **swing**: `9ee3ecd6`（重点,已知翻面）, `1c0ddc50`, `gpt4_194be4b3`, `d3ab962e`
  - **对照**: 2 个 stable-PASS（如某 knowledge-update / single-session-user 明确正确题）
    + 1 个 stable-FALSE/abstain
- 每三元组 judge-only 重判 **20× swing / 10× 对照**,统计 yes-rate / flip。
  - 关键诊断: 对 `9ee3ecd6` 用**逐字相同的那条 answer**重判,看 flip rate——这是纯 judge 噪声。
- 成本: ~7 三元组 × 10-20 = ~120-140 次 gpt-4o judge 调用,几分钟,**无 ingest、无 n=100**。
- 产出: 每三元组 yes-rate;判定哪些是 stable（0%/100%）哪些 flippy;judge 方差量级。

## 4. VR-1c 双口径定义（必须分清,不能混用）
| 口径 | 定义 | 用途 |
|---|---|---|
| **Mem0-compatible score** | 1 answer + 1 judge,逐字原协议 | 对齐公开 SOTA 的**唯一 headline 口径** |
| **Stability-adjusted score** | 固定 answer + N-judge majority,或 n-run mean±std | **内部**判断真实架构水平 |

**铁律**: N-judge majority / 多跑统计是"不作弊的稳定评估",但**协议不同**,
**绝不冒充 Mem0 同协议分数,绝不进 README headline**。报告时必须显式标注口径。

## 5. VR-1d 门槛（条件实现,本步不做）
仅当 VR-1b 证明 judge flip 明显时才实现,且作为 bench harness 选项:
`--judge-repeats N`（默认 **1**,保历史协议）+ `--judge-aggregation majority`。
不污染历史单判协议,不写 README headline。

## 6. 暂不做（本步纪律）
- 不改 answer self-consistency。
- 不为提分改 prompt。
- 不跑 3× n=100。
- 不实现 N-judge（先 VR-1b 量化）。
- 不改任何代码（本 log 纯 audit）。

## 7. 进度
- [x] VR-1a 只读 audit（本 log）: temp 已 0;非确定源 = OpenRouter 路由 + 模型内随机;
  无 seed/provider pin;retry 不额外引入方差;judge 份额待 VR-1b 量化。
- [ ] VR-1b judge-only repeat（设计完成,待授权执行）。
- [ ] VR-1c 报告双口径（VR-1b 后）。
- [ ] VR-1d N-judge（仅 flip 明显才做）。
