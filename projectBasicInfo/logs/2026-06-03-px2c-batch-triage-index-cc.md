# PX-2c — batch triage index（target-pack artifact → index.md + triage.json）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-03
> 前置: PX-2a audit（§4 关键约束）、PX-2b 增强单报告。
> 范围: 只对 target-pack artifact 做 **verdict-level preliminary triage**。
> 不伪造 `path_summary` layer，不自动跑 diagnose/ingest，不改 runtime，不碰 `src/radiomind`。

---

## 1. 目标
target-pack 红了之后，能一条命令生成一组可读报告：哪些 qid 红、各属什么 verdict 级
preliminary 类别、下一条命令是什么。

## 2. 核心约束（PX-2a §4，本步设计的地基）
target-pack artifact 的 `per_query` 记录**没有 `path_summary` / `diagnosis.layer`**，
只有 correct/judge_failed/answer/helper_hints。所以 batch index **只能给 preliminary
verdict-level 分类**，不能伪造 layer。真 layer 只在磁盘上已存在 `diagnose-<qid>.json`
时读出回填。index.md 头部用醒目 caveat 声明这一点。

## 3. 改动

### `bench/end_to_end/diagnosis_report.py`（纯函数）
- `classify_preliminary(present, correct, judge_failed, helper_hints, answer)` →
  PRELIM_MEANING key:
  - `pass` / `judge-infra` / `answer-error`（answer 以 `[answer error` 开头，
    infra 非逻辑结果）/ `trust-gap-candidate`（hint fired 但 abstain）/
    `abstain-no-hint` / `concrete-wrong-candidate` / `missing`。
- `build_triage_index(artifact_data, manifest, diagnose_dir, artifact_path)`:
  复用 `target_pack.summarize` 做 manifest 合并 + 计数；每 row 附 preliminary 标签 +
  answer snippet + fired hints + suggested_command；若 `diagnose_dir` 下有
  `diagnose-<qid>.json` 则 read-only 回填 `real_layer` + 记 `diagnose_json` 路径。
- `render_index_md(index)`: caveat 头 + required/observe 两表（列含 verdict /
  preliminary / layer(— 若无) / qtype / hints）+ "Next commands" 段（每红点给
  meaning + answer + suggested command）。
- `write_triage(index, out_dir, artifact_path)`: 写 `index.md` + `triage.json`；
  对有 diagnose json 的 row，额外复用 PX-2b 单报告管线生成 `<qid>/summary.md` +
  `diagnosis.json`（e2e_artifact 回填真路径）。单条失败不拖垮整体。
- `main()` 改为 `--diagnose-json`（单）/ `--target-pack-artifact`（批）互斥必选 +
  `--diagnose-dir`（默认 artifact 父目录）。

### `bench/end_to_end/devtools.py`
- `report` 子命令: `--diagnose-json` / `--target-pack-artifact` 互斥必选组 +
  `--diagnose-dir`。`plan()` 按模式构造 argv。

### `03_DEV_WORKFLOW.md`
- §4 triage flow 加 step 0：整盘红时先 `report --target-pack-artifact` 出 index，
  附 preliminary 非权威 layer 的提醒。

### 测试
- `tests/test_diagnosis_report.py` +7（classify 全类含 answer-error / index 行+计数 /
  real_layer 回填 / caveat 且不造假 layer / write_triage 落 index+json / per-qid 子报告）。
- `tests/test_devtools.py` +3（batch dispatch / diagnose-dir 转发 / 模式互斥）。

## 4. 验证（完成标准对照）
- ✅ 实测 `report --target-pack-artifact target-pack-result.json --out <dir>` 生成
  `index.md` + `triage.json`，required 6/8 gate FAIL 正确；preliminary 分类正确
  （pass / answer-error / concrete-wrong-candidate / abstain-no-hint）；caveat 头在；
  layer 列对无 diagnose json 的 qid 显示 `—`（不造假）；4 个有 diagnose json 的 qid
  生成了 per-qid 子报告。
- ✅ 每个红点有 line / verdict / preliminary / meaning / 下一条命令。
- ✅ answer-error 诚实标注（bb7c3b45/c18a7dc8 的 `[answer error: urlopen…]` 不再被误判
  为 concrete-wrong）。
- ✅ regression pack 全绿（`diagnostic:report 28`）。
- ✅ 无 `src/radiomind` diff，未自动跑 diagnose，未跑 benchmark。

## 5. PX-2 整体收尾
| 步 | 产物 | 状态 |
|---|---|---|
| PX-2a | audit（关键约束: artifact 无 layer） | done |
| PX-2b | 自包含单报告（Q/gold/answer/verdict/manifest/suggested cmd + 两 layer next_action 细化） | done（已 commit 823b45a） |
| PX-2c | batch triage index（preliminary 分类 + index.md/triage.json + per-qid 子报告） | done |

devtools report 现双模式: 单 qid 深报告 / 整盘 preliminary triage。纪律守住:
`src/` 零改动、不自动 ingest、不跑 benchmark。
