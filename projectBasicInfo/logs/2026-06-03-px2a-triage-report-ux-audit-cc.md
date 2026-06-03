# PX-2a — Diagnosis Report UX + batch triage 只读 audit

> 作者: Claude Code (cc) ｜ 日期: 2026-06-03
> 前置: PX-1（devtools CLI + `diagnosis_report.py`）。
> 范围: **只读盘点 + 设计**。不改 runtime，不跑 benchmark，不改 tooling 代码（本步只产出 audit log）。

---

## 1. 目标
评估现有 `diagnosis_report.py` 输出（`summary.md` / `diagnosis.json`）缺什么，
设计把它从"单报告投影器"升级成"失败 triage 报告系统"（PX-2b 增强单报告 + PX-2c 批量 index）。

## 2. 现状基线（实测产物）

### 当前 `summary.md`（WRONG 案例 c18a7dc8-dx2b 实际渲染）
```
# diagnose c18a7dc8 — WRONG
**Layer:** `answer_or_judge_path`
**Meaning:** ...
**Fix family:** ...   **Do not:** ...   **Next action:** ...
**Reason:** ...
- retrieval: gold 5/200, 5/30
- e2e: WRONG
_source: bench/end_to_end/diagnose-c18a7dc8-dx2b.json_
```

### 当前 `diagnosis.json` 字段
`qid, layer, reason, meaning, fix_family, do_not, next_action, layer_recognized,
source, context{retrieval, verdict, flags}`

### target-pack artifact（PX-2c 的输入）真实结构
- top-level: `overall_accuracy / raw_accuracy / judged_accuracy / judge_error_rate /
  by_type / per_query / answer_model / judge_model / ...`
- **`per_query[]` 每条**: `question_id, q, gold, answer, correct, qtype,
  verdict_tail, judge_failed, helper_hints{savings,person_age,cashback,role_guard,
  temporal_endpoint,answer_pure_abstain}`

## 3. 审计结论（回答 4 个问题）

### Q1. 能否一眼看懂 qid 为什么红？
**部分**。summary.md 有 layer + meaning + reason，能看懂"哪一层/为什么"，但**看不到红的具体内容**:
- ❌ 没有 question 文本（不知道这题在问什么）
- ❌ 没有 answer snippet（只说 "WRONG"，看不到模型答了什么错的）
- ❌ 没有 gold（无法对照对错）
- ❌ 没有 manifest line（不知道这 qid 代表哪条 committer/suppressor/hint 线）
→ 必须回去翻原始 diagnose json 才能看到答案。这是单报告最大缺口。

### Q2. 能否看到 source artifact / e2e verdict / answer snippet？
- ✅ source artifact: 有（`_source:` 行）。
- ✅ e2e verdict: 有（`- e2e: WRONG [flags]`）。
- ❌ answer snippet: **没有**。`final_answer.answer` 其实存在于 diagnose json
  （截断 160），但 `build_diagnosis_report` 没把它放进 context，`render_summary_md`
  也没渲染。**最该补的一项。**

### Q3. 能否直接知道下一条命令？
**否**。报告给了 fix_family/do_not/next_action（方向性文字），但**没有可复制的命令**。
开发者读完还要自己拼 `devtools diagnose --qid ... --e2e-result ...`。
→ PX-2b 应加 `suggested_command` 字段（qid 实填）。

### Q4. 哪些 layer 的 next_action 太泛？
逐条看 `LAYER_GUIDANCE`:
- `concrete_wrong_bypassed_committer`: "audit hint trust upstream, or consider a
  suppressor-shaped guard; verify with a fresh run" —— **偏泛**。没说去读哪个字段
  （应指向 `closure_view.committers.<name>` 看哪个 committer ready、读 answer 看
  它具体答了什么 concrete-wrong）。
- `proof_input_turn_missing`: "audit retrieval granularity / ranking..." —— **偏泛**。
  应指向 `retrieve_top_30_preview` 看 gold turn 排到第几、`helper_proofs.<helper>.refusal_reason`
  看缺哪个 anchor。
- `answer_or_judge_path`: 已较具体（infra retry vs trust）。
- `helper_refusal` / `retrieval_gap` / `closure_ready` / `pass` / `unknown`: 够用。
→ PX-2b 优先把上面两条 layer 的 next_action 写成"去读哪个字段 + 该字段说明什么"。

## 4. PX-2c 的关键约束（本 audit 最重要的发现）

**target-pack artifact 的 per_query 记录里没有 `path_summary` / `diagnosis.layer`。**
layer 只存在于 diagnose-<qid>.json（由 `diagnose_qid.py` 重跑 ingest+LLM 产生）。

实测 target-pack-result.json 的 per_query 可得信号（10 qid）:
```
qid                 correct judge_failed abstain hints
gpt4_d12ceb0e       True    False        False   [person_age]
bb7c3b45            False   False        False   []
c18a7dc8            False   False        False   []
b46e15ed            False   False        True    []
gpt4_7abb270c       False   False        False   []
031748ae_abs        True    False        True    [role_guard]
...
```

**推论**: PX-2c 的 batch index 在"不自动跑 diagnose"的约束下，**只能产出 verdict 级
preliminary triage**，不能给完整 layer。它能给的:
- manifest line + mode（required/observe_only） + present/correct/verdict
- qtype / gold / answer snippet（per_query 直接有）
- 哪些 helper_hint fired + 是否 pure_abstain
- **基于以上的 preliminary 分类**（纯规则，明确标注"非最终 layer"）:
  - correct=True → `pass`
  - judge_failed=True → `answer_or_judge_path (judge infra)`
  - abstain=True 且无 hint → `abstain (no hint fired)`
  - abstain=True 且有 hint → `trust-gap candidate (hint fired but abstained)`
  - 具体错 (wrong, not abstain) → `concrete-wrong candidate`
- 每个红点的**下一条命令**: `devtools diagnose --qid <q> --e2e-result <artifact>` → `devtools report ...`
- **可选增强**: 若磁盘上已有 `diagnose-<qid>.json`，从中读真 layer 回填（标注来源）。

这条约束必须写进 index.md 头部，避免误读 preliminary 分类为权威 layer。

## 5. PX-2b 设计草案（增强单报告）

`build_diagnosis_report` 扩 context（仍从 diagnose json 投影，不新探针）:
- `question`（从 diagnose rec top-level `question`）
- `gold`（`gold`，截断）
- `answer_snippet`（`path_summary.final_answer.answer`，截断）
- `manifest_line`（可选: 若能从 target_pack.MANIFEST 反查 qid → line）
- `suggested_command`: e.g.
  `python -m bench.end_to_end.devtools diagnose --qid <qid> --e2e-result <artifact>`
  （artifact 来源: 若 report 是从 batch 模式生成则带 artifact 路径，否则给占位）

`render_summary_md` 增段:
```
# diagnose <qid> — <verdict> (<manifest_line>)
**Q:** <question>
**Gold:** <gold>     **Answer:** <answer_snippet>
**Layer:** ...  (+ meaning/fix_family/do_not/next_action 不变)
...
**Suggested next:**
    <suggested_command>
```
两个偏泛 layer 的 next_action 改写为"读哪个字段"。

`diagnosis.json` 新增字段: `question, gold, answer_snippet, suggested_command,
manifest_line`。**向后兼容**: 旧字段全保留，测试只新增断言不改旧断言。

## 6. PX-2c 设计草案（batch triage index）

新 report 子模式（`diagnosis_report.py` 加函数 + devtools 加参数）:
```
python -m bench.end_to_end.devtools report \
  --target-pack-artifact bench/end_to_end/target-pack-result.json \
  --out reports/target-pack-<date>
```
（注: report verb 现有 `--diagnose-json`；PX-2c 加互斥的 `--target-pack-artifact`。
日期由 caller 传，脚本内不取系统时间——遵守 workflow 纪律。out 目录名的日期由用户给。）

纯函数:
- `build_triage_index(artifact_data, manifest, diagnose_dir=None) -> dict`
  复用 `target_pack.summarize` 做 manifest 合并；每 qid 附 preliminary 分类 +
  suggested_command；若 `diagnose_dir` 下有 `diagnose-<qid>.json` 则回填真 layer。
- `render_index_md(index) -> str`
- `write_triage(index, out_dir) -> paths`

产物:
- `index.md`: 头部声明（preliminary，非权威 layer）+ required/observe 两组表
  （qid | line | verdict | preliminary | qtype | hints | suggested cmd）
- `triage.json`: 机器可读汇总（rows + counts + required_all_pass）
- （每 qid 一个 summary.md：**仅当**对应 diagnose json 存在时生成，否则只在 index 里
  给"先跑 diagnose"的命令——不自动跑 ingest）

**不做**: 不自动 `diagnose`（不 ingest/LLM）、不跑 benchmark、不改 runtime。

## 7. 完成标准（供 PX-2b/2c 验收）
- 单 report 更好读（带 Q/gold/answer/suggested command）。
- target-pack artifact → 一个 `index.md` + `triage.json`。
- 每个红点有 line/verdict/preliminary 分类/meaning/next action/下一条命令。
- regression pack 全绿（新增 batch 测试 + 增强单报告测试）。
- 无 `src/radiomind` diff，不跑 full benchmark。

## 8. 下一步
进 **PX-2b**: 增强 `build_diagnosis_report` + `render_summary_md`（Q/gold/answer/
suggested_command + 两个 layer next_action 细化），扩 `test_diagnosis_report.py`。
再 **PX-2c**: batch index。两步都只动 `diagnosis_report.py` / `devtools.py` / tests / 文档。
