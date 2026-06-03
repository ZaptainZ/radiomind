# PX-2b — 增强单个 diagnosis report（自包含 summary.md）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-03
> 前置: PX-2a audit。范围: **只增强单报告**。不做 batch index，不自动跑 diagnose，
> 不改 `diagnose_qid.py`，不改 runtime，不碰 `src/radiomind`。

---

## 1. 目标
让 `devtools report` 生成的 `summary.md` 自包含——直接回答："这个 qid 问什么、gold
是什么、模型答了什么、为什么红、下一步命令是什么"，无需回翻原始 diagnose json。

## 2. 改动（仅 `bench/end_to_end/diagnosis_report.py` + 测试）

### `build_diagnosis_report(data, source, manifest_line=None, e2e_artifact=None)`
context 扩字段（全部从 diagnose rec 投影，无新探针）:
- `question` / `gold` / `qtype`（diagnose rec top-level，`_trunc` 截断）
- `answer_snippet` / `correct` / `judge_failed` / `answer_pure_abstain`（来自
  `path_summary.final_answer`；无 overlay 时为 None）
- `manifest_line`（target_pack.MANIFEST 反查 qid → line，如 `age-interval-committer`）
- `source_artifact`（= source diagnose json 路径）
- `suggested_command`（qid 实填的 `devtools diagnose --qid <qid> --e2e-result <art>`；
  `e2e_artifact` 为 None 时用占位 `<e2e-result.json>`，供 PX-2c batch 模式回填真路径）
- 保留 `retrieval` / `verdict` / `flags`（向后兼容）

### 新增 `lookup_manifest_line(qid) -> str|None`
best-effort 从 `target_pack.MANIFEST` 反查（lazy import，sys.path 注入 bench 目录），
任何失败返回 None，绝不抛。

### `render_summary_md` 重构为自包含布局
```
# diagnose <qid> — <verdict> (<manifest_line>)
**Question/Type/Gold/Answer/Verdict**
## Diagnosis  (Layer/Meaning/Fix family/Do not/Next action/Reason + retrieval)
## Next command  (```bash <suggested_command> ```)
_source: <...>_
```
无 e2e overlay 时 Verdict 显示 "n/a (re-run with --e2e-result)"。

### 细化两个偏泛 layer 的 next_action
- `concrete_wrong_bypassed_committer`: 指明读 `final_answer.answer`（concrete wrong 值）
  + `closure_view.committers.<name>`（proof 是否 ready）确认 bypass，再审 upstream
  hint-trust / suppressor-shaped guard，**绝不动 committer**。
- `proof_input_turn_missing`: 指明读 `helper_proofs.<helper>.refusal_reason`（缺哪个
  anchor）+ `retrieve_top_30_preview`（gold turn 排第几）确认 proof turn 没进窗口，再审
  retrieval granularity/ranking，**不动 parser**。

### 向后兼容
旧 diagnose json 缺 question/gold/final_answer → 对应字段 None、summary 段落省略，
不崩。`_trunc(None,...)` 安全返回 ""。旧测试断言全保留未改。

## 3. 修改文件
- 改 `bench/end_to_end/diagnosis_report.py`
- 改 `tests/test_diagnosis_report.py`（+11 测试，现 22）
- 新增 PX-2a audit log（本轮）+ 本 log
- **`src/` 零改动**，regression_pack.py 未改（diagnostic:report 类别已存在）。

## 4. 验证（完成标准对照）
- ✅ 实测 `report --diagnose-json diagnose-c18a7dc8-dx2b.json` 生成的 summary.md 直接答全
  五问：Question="How many years older…"、Gold=7、Answer="…not enough."、Verdict=WRONG、
  Next command 带 `--qid c18a7dc8`；标题自动带 `(age-interval-committer)`。
- ✅ 旧 artifact（无 path_summary）仍可报告：layer=unknown，question/gold 仍从 top-level
  取到，Verdict=n/a，不崩。
- ✅ 新增测试覆盖 context 字段 / suggested_command(占位+真路径) / manifest 反查(c18a7dc8→
  age-interval-committer)+override+未知 qid / 自包含 summary / next_action 细化 / legacy 不崩。
- ✅ regression pack 全绿（`diagnostic:report 22 passed`）。
- ✅ 无 `src/radiomind` diff，未跑 benchmark。

## 5. 下一步
进 **PX-2c**: batch triage index。report 加互斥参数 `--target-pack-artifact`，复用
`target_pack.summarize` 合并 manifest，产出 `index.md` + `triage.json`。
**关键约束（PX-2a §4）**: target-pack artifact 无 per-qid layer，batch 只能给 verdict 级
preliminary 分类 + 下一条命令，可选从磁盘已有 diagnose json 回填真 layer；不自动跑 ingest。
