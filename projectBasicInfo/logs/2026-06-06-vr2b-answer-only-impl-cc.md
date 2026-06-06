# VR-2b — bench-only answer-only mode 实现

> 作者: Claude Code (cc) ｜ 日期: 2026-06-06
> 范围: 只改 `bench/end_to_end/run_longmemeval_mem0.py` + 测试。不碰 src/radiomind,
> 不改 prompts/temperature/judge。默认行为不变。前置: VR-2a audit。

---

## 1. 改动
仅 `run_longmemeval_mem0.py`:
- 新增 CLI: `--answer-only` + `--reuse-existing-sandbox`（均默认关闭）。
- 新增纯函数 `_validate_answer_only(answer_only, reuse, qids) -> str|None`:
  - `--answer-only` 必须配 `--reuse-existing-sandbox`,否则 error exit 2。
  - `--answer-only` 必须配 `--qids`（domain=lme_{q_idx} 顺序耦合）,否则 exit 2。
  - `--reuse-existing-sandbox` 单独出现（无 answer-only）也报错（无意义,防误用）。
- `run()` 加 `answer_only: bool=False`:
  - 清库门控: `if not answer_only and (sandbox/"data").exists(): rmtree`。
  - ingest 门控: `if answer_only: stats={"ingested":0}` else 原 `ingest_turns_raw`。
  - 空检索 hard fail: `if answer_only and not results: raise SystemExit(...)`
    （复用 sandbox 未 seed 该 domain 时立即失败,不静默用空 store 答题）。
- 其余（config 写入、search、answer 组装、gate、judge）**逐字不变**。

## 2. 不变量
- 默认（不传新 flag）→ 行为与改动前完全一致（regression pack 全绿验证）。
- answer-only 隔离的方差 = answer-LLM + BidirectionalAbstainGate-LLM + judge（store 固定）。
- 复用要求: `--sandbox` 指向一次**相同 `--qids` 顺序**普通 run 产生的已 seed sandbox。

## 3. 测试（`tests/test_vr2b_answer_only.py`,8 项,确定性,无真 ingest）
- `_validate_answer_only` 五种组合（默认 OK / reuse-only 报错 / 缺 reuse / 缺 qids / 全配 OK）。
- `inspect.signature(run)` 有 `answer_only` 且默认 False。
- 源码守卫: run 用 `not answer_only` 门控清库、`if answer_only` 跳 ingest、空检索 hard fail。
- main 暴露两个 flag + 调 `_validate_answer_only` + 传 `answer_only=args.answer_only`。
- 挂进 regression_pack `harness:vr2b-answer-only`。

## 4. 验证
- VR-2b 测试 8/8 passed。
- invalid 组合实测 exit 2 + 清晰报错,且**在 ingest/mind-init 之前**就退出（无重操作）。
- regression pack 全绿（新增类 + 既有 28 类）。
- 无 `src/radiomind` diff。

## 5. 下一步
VR-2c 实验（小样本）: seed 1× → fixed-store answer-only 5× → fresh full 3×,
对比 answer-path 方差 vs ingest+answer 合并方差。
