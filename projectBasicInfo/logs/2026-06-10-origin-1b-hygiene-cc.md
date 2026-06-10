# Origin-1b-hygiene — DELTA 去题化 + 截断残桩重试 + section 观测字段

> 作者: Claude Code (cc) ｜ 日期: 2026-06-10
> 前置: Origin-1a/3a 原点审计（同日 log）。用户裁决: ①②③ 一批做（基准卫生 + harness
> 鲁棒性 + 可观测性），Origin-3b 做梦探针**单独开**不混批; Origin-1b shape guidance
> 维持不立项（证伪成立）。
> 范围: bench-side only，零 `src/radiomind` 改动。不跑 n=100。

---

## 1. 三项改动

### ① DELTA 算例去题化（benchmark hygiene）
`bench/end_to_end/mem0_protocol/longmemeval_prompts.py` DELTA vs ABSOLUTE 规则的
算例数字 `200/300→100`（源自 fail qid 9ee3ecd6 原题）改为无关数字 `50/120→70`。
规则本身保留。**预期可能丢 9ee3ecd6 仅有的 1/3 pass——不追**（用户裁决: 北极星
"不针对题目特调"优先于这 1/3 个 pass）。

### ② 截断残桩检测 + 单次 regen（harness 鲁棒性）
`run_longmemeval_mem0.py`:
- `_is_truncated_stub(answer)`: 仅命中 (a) strip 后空串; (b) 无句末标点 **且** 末词
  落在小型闭集（冠词/介词/连词/助动词/物主代词/I/you/currently/own 等不能结句的词）。
  `$300` / `7` / `8 miles` / `four` / canonical abstain / `[answer error: …]` 均不触发
  （单测全覆盖负例）。
- `_answer_with_retry` 拆为 `_answer_once_with_transient_retry`（原异常重试逻辑不变）
  + 外层 stub 检测: 命中则**单次** regen,二次仍 stub 取较长者,绝无第三次。
- Telemetry: 返回 `(answer, retry_reason)`,触发时 per_query 记
  `answer_retry_reason="truncated_stub"`,未触发不写字段。

### ③ prompt_sections 观测字段（可观测性）
per_query 新增独立字段（**不**塞进 helper_hints,prompt section ≠ helper fire）:
```json
"prompt_sections": {"cardinal_present": bool, "cardinal_chars": int,
                    "atomic_present": bool, "atomic_chars": int}
```
纯函数 `_prompt_sections_record(cardinal_section, atomic_section)`。用途: S2
（decomposer trinity 化）的立项前提——"decomposer 没触发 vs 触发了但产出错"——
此前 artifact 无法判定;下次 n=100 起自然积累证据。

## 2. 验证
- 新增 `tests/test_origin1b_hygiene.py`（11 tests）: 去题化断言（旧数字组合不存在 +
  新算例算术一致 + 规则仍在）、stub 正负例、单次 regen + telemetry、双 stub 不三试、
  异常→stub→clean 组合路径、prompt_sections 字段契约。
- `tests/test_answer_retry.py` 同步 tuple 返回（3 tests 保留原断言 + reason=None）。
- regression pack 新增 `harness:origin1b-hygiene` 类目 → **21 类 ALL PASS**。
- 未跑 n=100（按裁决）。①的分数影响留待下次 formal baseline refresh 观察,不单独验证。

## 3. 改动文件
`mem0_protocol/longmemeval_prompts.py` / `run_longmemeval_mem0.py` /
`regression_pack.py` / `tests/test_answer_retry.py` / `tests/test_origin1b_hygiene.py`(新)

## 4. 不做 / 守住
不开 Origin-1b shape guidance（已证伪）。不把 stub 检测扩成泛化"答案质量校验"。
Origin-3b（`--dream-after-ingest` 2-qid 探针）单独开线,成功标准是窗口稳定性而非分数,
未跑前不得宣传"会涨分"。
