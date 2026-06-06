# VR-2a — bench runner answer-only 能力审计 + 最小设计（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-06
> 目标: 拆分 answer-side 方差 vs ingest/refinement 方差（VR-1b 已排除 judge 为主力）。
> 范围: 只读 audit + 设计。不改代码。前置: `2026-06-06-vr1b-*`（judge 非主力）。

---

## 1. runner 现状（`run_longmemeval_mem0.py`）

| 能力 | 现状 | 位置 |
|---|---|---|
| 复用已有 sandbox / store | **无** | — |
| 跳过 ingest | **无** | — |
| 只跑 selected qids | 有（`--qids`） | main → `qids_filter` → line 301-313 |
| 只重 answer+judge | **无** | — |
| 续跑（resume） | 有,但**整题跳过**（连 answer 不跑） | `done_qids` line 419-420（checkpoint 恢复用,不能隔离 answer-side） |

**两个硬拦路点**:
1. `run()` line 222-224: **无条件** `shutil.rmtree(sandbox/"data")` 清库 —— 每次调用都毁掉已有 store。
2. ingest 在 per-qid 循环内: line 450 `mind.ingest_turns_raw(...)` —— 无开关跳过。

**关键耦合（设计必须遵守）**:
- line 422 `domain = f"lme_{q_idx}"`,`q_idx` = enumerate 在 **errata+qids 过滤后 data 列表**
  里的位置索引,**不是 qid**。
- 推论: answer-only 复用一个已 ingest 的 sandbox 时,**必须用与 seed 完全相同的 `--qids`
  集合与顺序**,否则 `lme_{q_idx}` 对不上、search 命中错 domain。
- 同一 `--qids` 下,过滤后顺序 = dataset 顺序的稳定子集 → q_idx→domain 可复现（done_qids
  跳过不影响 enumerate 计数,故 domain 索引稳定）。

**复用可行性前提**: ingest 的产物（L2 turn / KG / L3 principle / Meta）持久化在
`sandbox/data` 的 SQLite store；新进程 `mind.initialize()` 指向同一 RADIOMIND_HOME 即可
加载。answer-only 模式据此跳过 ingest 仍能 `mind.search(domain=...)` 命中。
→ VR-2b 须加一个守卫: 复用后首个 search 若返回空,立即报错（防止把"空 store 误当稳定"）。

## 2. VR-2b 最小设计（bench-only,默认关闭,不碰 src/radiomind）

仅改 `bench/end_to_end/run_longmemeval_mem0.py`:
1. argparse 加 `--answer-only`（`action="store_true"`,默认 False）。
2. `run()` 加形参 `answer_only: bool = False`;main 传 `answer_only=args.answer_only`。
3. line 223-224 清库: 改为 `if not answer_only and (sandbox/"data").exists(): rmtree`。
4. line 450 ingest: `if answer_only: stats = {"ingested": 0}` else 原 `ingest_turns_raw(...)`。
5. （守卫）answer_only 且某 domain `mind.search` 返回空 → print 警告并标记该 qid,
   避免静默把空检索当结果。
6. 其余（config 写入、search、answer 组装、gate、judge）**完全不变**。

**不变量**:
- 默认（不传 `--answer-only`）→ 行为与现在逐字一致（普通 n=100 不受影响）。
- 不碰 `src/radiomind`。
- 复用语义: answer_only 复用 `--sandbox <existing>`,要求该 sandbox 由一次**相同 `--qids`**
  的普通 run 产生。

**answer-only 模式隔离的方差**: 固定 store（embedding/rerank/search 对固定 store 确定）
→ 重复 answer-only 的差异 = **answer-LLM 采样 + BidirectionalAbstainGate 的 LLM + judge**。
（judge 已知低噪,gate 也是 answer-path LLM）→ 即 "answer-path 方差"。

## 3. VR-2c 实验设计（VR-2b 实现后执行）
qid 集: 4 swing（9ee3ecd6/1c0ddc50/gpt4_194be4b3/d3ab962e）+ 2 stable（e9327a54/caf9ead2）。

1. **seed**: 普通 run 一次,`--qids <6 个,固定顺序> --sandbox S`（ingest+answer+judge）。
2. **fixed-store answer-only ×5**: `--qids <同 6 个同序> --sandbox S --answer-only` ×5
   → **answer-path 方差**（store 固定）。
3. **fresh full ×3**: fresh sandbox ×3,普通 run → **ingest+answer 合并方差**。
4. 对比:
   - fixed-store 也大幅波动 → **answer generation 是主因**（杠杆: answer temperature↓ / self-consistency）。
   - fixed-store 稳但 fresh 波动 → **ingest/refinement 是主因**（杠杆: refinement 确定性 / 检索稳定）。

样本量（先小）: answer-only 5×/qid,fresh 3×/qid,仅 6 qid。不跑 n=100。

## 4. 不做
不改 temperature、不做 self-consistency、不跑 n=100、不写 README、不开 fix、不碰 src。

## 5. 结论 / 下一步
- answer-only 复用**可行**,改动面**极窄**（1 文件、2 处 guard、1 flag、默认关闭）。
- 主要风险 = `domain=lme_{q_idx}` 的顺序耦合 → 用固定 `--qids` 顺序规避 + 空检索守卫。
- **建议实现 VR-2b**（含一个 deterministic 测试: 断言默认 `answer_only=False`、
  argparse 暴露 `--answer-only`、answer_only 时不调 ingest/不清库——用 introspection /
  轻量 mock,不跑真 ingest）。然后执行 VR-2c。

## 6. 进度
- [x] VR-2a audit + 最小设计（本 log）。
- [ ] VR-2b 实现 `--answer-only`（待授权）。
- [ ] VR-2c answer-path vs ingest 方差对比实验。
