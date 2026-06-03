# PX-1c — 标准 diagnosis report（diagnosis.json + summary.md）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-03
> 前置: PX-1a audit（§5 报告设计）、PX-1b devtools dispatcher。
> 范围: 只做 report 层。**不重跑 diagnose，不改 `diagnose_qid.py`，不改 runtime，
> 不碰 `src/radiomind`，不让 report 触发 benchmark/ingest。**

---

## 1. 目标
把现有 diagnose JSON 投影成稳定、人能直接读的报告：`diagnosis.json` + `summary.md`，
其中 `recommended_next_action` 只做**纯查表**（DX-2c 已稳定的 `diagnosis.layer` →
fix_family/do_not/next_action），不做任何新推理。

## 2. 实现要点

### 新增 `bench/end_to_end/diagnosis_report.py`（纯模块）
- `LAYER_GUIDANCE`: layer → {meaning, fix_family, do_not, next_action} 常量表。
  知识全部搬自 DEV_WORKFLOW §4 / PX-1a §5.4，覆盖完整 DX-2c 枚举:
  `pass / answer_or_judge_path / concrete_wrong_bypassed_committer /
  proof_input_turn_missing / helper_refusal / retrieval_gap / closure_ready /
  proof_ready / skill_route_gap / unknown`。
- `load_diagnose_json(path)` — 纯 IO。
- `build_diagnosis_report(data, source)` — 纯投影。从 `path_summary.diagnosis.layer`
  取 layer/reason，查表填 fix_family/do_not/next_action/meaning，附 compact `context`
  （retrieval gold 命中 + e2e verdict/flags，**不**灌完整 diagnose rec）。
  - **关键鲁棒性**: 老 diagnose JSON（DX-2a 之前）**没有 `path_summary`**（实测
    `diagnose-c18a7dc8.json` ps 为空，而 `diagnose-c18a7dc8-dx2b.json` 才完整）。
    缺失时优雅降级到 `layer="unknown"` + 明确 note，绝不 crash。
  - 未识别的 layer → 回退 `unknown` 指引 + `layer_recognized=False` 标记。
- `render_summary_md(report)` — 纯渲染人读 md。
- `write_report(report, out_dir)` — 写 `diagnosis.json` + `summary.md`，返回路径。
- `main()` — argparse `--diagnose-json`/`--out`（均 required），load→build→write。
  **纯文件 IO，无 ingest/LLM/benchmark。**

### diagnosis.json 稳定 schema
`qid, layer, reason, meaning, fix_family, do_not, next_action, layer_recognized,
source, context{retrieval, verdict, flags}`（含任务要求的 qid/layer/reason/
fix_family/do_not/next_action/source 全部字段）。

### 接入 `bench/end_to_end/devtools.py`
- 新增 `report` 子命令 → `Dispatch("report","diagnosis_report",
  ["--diagnose-json",...,"--out",...])`，复用 PX-1b 的 `run()` 通用转发，零特例。
  ```
  python -m bench.end_to_end.devtools report --diagnose-json <json> --out <dir>
  ```

### 测试
- 新增 `tests/test_diagnosis_report.py`（12 测试，小 JSON fixture，无 ingest/LLM）:
  每个必需 layer 都有完整指引、投影正确、legacy 缺 path_summary 降级、未识别 layer
  回退+标记、context verdict/flags 提取、summary.md 核心字段、write_report 落两文件+round-trip。
- `tests/test_devtools.py` 补 2 个 `report` dispatch 测试（required 校验 + module/argv 映射），现 14 测试。
- `regression_pack.py` PACK 新增 `diagnostic:report → tests/test_diagnosis_report.py`。

## 3. 修改文件
- 新增 `bench/end_to_end/diagnosis_report.py`
- 新增 `tests/test_diagnosis_report.py`
- 改 `bench/end_to_end/devtools.py`（+report 子命令 + dispatch）
- 改 `tests/test_devtools.py`（+2 report 测试）
- 改 `bench/end_to_end/regression_pack.py`（+1 PACK 项）
- 新增本 log
- **`src/` 零改动** → runtime 未触碰。

## 4. 遇到的问题
- 老 diagnose JSON 无 `path_summary`（DX-2a 之前的产物）。build 必须降级而非崩溃——
  已用 fixture 测 `test_legacy_rec_without_path_summary_degrades_to_unknown` 钉死。

## 5. 验证（完成标准对照）
- ✅ `devtools report --diagnose-json <real dx2b> --out <dir>` 生成两个文件（实测
  c18a7dc8-dx2b → `answer_or_judge_path`，summary.md 含 retrieval 5/200 + e2e WRONG）。
- ✅ 每个核心 `diagnosis.layer` 都有 fix_family/do_not/next_action（表 + 测试覆盖）。
- ✅ legacy artifact 优雅降级到 `unknown` 并给出 next_action（实测 c18a7dc8 旧文件）。
- ✅ regression pack **全绿**（`harness:devtools 14` + 新 `diagnostic:report 12`）。
- ✅ 仍是纯 bench/dev tooling，无 runtime diff（`src/` 未动）。

## 6. 下一步
**PX-1d**: 更新 `03_DEV_WORKFLOW.md`（把 devtools 4 命令写进操作手册）+ README 开发者段 +
（report parser 的确定性测试本步已含，可在 1d 复核）。这是 PX-1 收尾的文档/smoke 步。
