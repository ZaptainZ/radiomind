# PX-1a — Productization 只读 audit：devtools CLI + 标准 diagnosis report schema 设计

> 作者: Claude Code (cc) ｜ 日期: 2026-06-03
> 范围: **只读盘点 + 设计**。不改 runtime，不改 retrieval/helper/closure/scoring，不跑 benchmark。
> 后续: 本 log 通过后再决定是否进 PX-1b（CLI wrapper）。

---

## 1. 背景与目标

现状: 项目有一批**强诊断工具**（`regression_pack` / `target_pack` / `diagnose_qid` +
其内部的 `path_summary` / `closure_view`），但它们仍是 **bench 工具形态**——
路径深、调用口径靠 `03_DEV_WORKFLOW.md` 口头约定、输出是给人读的 stdout + 一坨
混合 schema 的 JSON。

PX-1 这条线的目标: 把"一堆强工具"整理成"一个开发者能稳定使用的诊断系统"。
PX-1a 只做**盘点 + 设计**，回答 4 个问题:

1. 哪些命令应成为标准 CLI？
2. 哪些输出字段是稳定 schema？
3. 哪些字段只是 debug/internal？
4. 当前最小产品入口是什么？

---

## 2. 入口盘点（只读）

### 2.1 `bench/end_to_end/regression_pack.py`
- **形态**: 纯 orchestrator。`PACK` = {category → test files}，对每个 category
  `subprocess` 跑 `pytest -q`，聚合 PASS/FAIL，exit 0 iff 全绿。
- **依赖**: 仅 pytest + 仓库内 test 文件。**无 ingest / 无 LLM / 无 dataset / 无 sandbox**。
- **纯度**: 完全确定性、可在任何机器无副作用跑。是"每次必跑"的 gate。
- **当前覆盖**: 16 个 behaviour category（committers/suppressors/hints/SelfAnchor/
  JAB/skills/harness/diagnostics）。
- **CLI 适配性**: ★★★ 最高。零外部依赖，最适合做第一个 devtools 子命令。

### 2.2 `bench/end_to_end/target_pack.py`
- **形态**: 双模式。
  - 默认: `subprocess` 跑 `run_longmemeval_mem0.py --qids <MANIFEST>`（真 ingest+LLM+judge，重），再 `summarize`。
  - `--report <json>`: **纯函数** `summarize(per_query, MANIFEST)` 直接读已有结果 json，不跑。
- **依赖**: 默认模式重度依赖 dataset / sandbox / LLM profile；`--report` 模式仅依赖一个结果 json。
- **关键设计**: `MANIFEST` 用 `mode` 把 `required`（gate exit code）和
  `observe_only`（parked，永不变红）分开。`summarize` 是纯函数、已被
  `tests/test_target_pack.py` 覆盖。
- **CLI 适配性**: `--report` 子路径 ★★★（纯、快、确定性）；默认运行路径 ★（重、需授权）。
  → devtools 里应**只暴露 `--report` 解析能力**为标准命令，运行真 e2e 仍走原脚本/手动授权。

### 2.3 `bench/end_to_end/diagnose_qid.py`
- **形态**: 单 qid 的分层显微镜。流程: ingest 一个 qid 的 haystack 到独立
  domain → retrieve top-200 → 逐 helper 探针 → SelfAnchor 探针 → store anchor
  探针 → `closure_view` what-if → `build_path_summary` 投影 → 可选 `--e2e-result` overlay。
- **依赖**: **重**。需要 dataset (`~/Library/Caches/radiomind-data/longmemeval_s_cleaned.json`)、
  从 `~/.radiomind/config.toml` 拷一份到 `/tmp/rm-diagnose-qid-<qid>` sandbox、
  真 ingest + 真 LLM (`llm_call` deepseek-v3.2)。
- **纯函数子集**（**这是产品化的金矿**，全部已有 deterministic 测试）:
  - `build_path_summary(rec, e2e=None)` — 纯投影，无探针无 LLM（`tests/test_path_summary.py`）。
  - `_classify_layer` / `_overlay_e2e` / `_extract_final` — 纯分类逻辑。
  - `_probe_closure_view` — what-if（调真 proof builder，但只读、不改 ordering；`tests/test_closure_view.py`）。
  - `_print_path_summary` / `_print_closure_view` — 渲染。
- **CLI 适配性**: 完整 diagnose 运行 ★（重、需 LLM）；但**对一个已存在的 diagnose-<qid>.json
  重新渲染/重投影 path_summary** 是 ★★★（纯）。

### 2.4 `path_summary`（`diagnose_qid.build_path_summary` 的产物）
- 不是独立文件，是 `diagnose_qid.py` 内的**纯投影函数**，把 diagnose record 的各 section
  （retrieval / helper_proofs / closure_view / skill route / 可选 e2e final）压成一个
  **失败定位**对象: `{qid, retrieval, deterministic_layer, skill_route, closure_decision,
  diagnosis:{layer,reason}, final_answer?}`。
- 这是整个诊断系统**最接近产品输出**的东西——它已经回答了"这个 qid 在哪一层挂了"。
- DX-2c 已把 `diagnosis.layer` 收敛成一组确定标签（见 §4 schema）。

### 2.5 `closure_view`（`diagnose_qid._probe_closure_view` 的产物）
- diagnose record 的一个 section: `{committers:{cashback,age_interval}, suppressors:{role,temporal_endpoint}}`，
  每项带 `would_commit_on_canonical_abstain` / `would_overwrite_concrete_answer` /
  detection 等 what-if。
- 是 committer-vs-suppressor 推理的决定性 section（见 DEV_WORKFLOW §3）。
- 只在 current-build 的 diagnose rec 上存在（历史 rec 没有）。

---

## 3. 审计结论（回答 4 个问题）

### Q1. 哪些命令应成为标准 CLI？

按"纯度 + 使用频率"排序，**3 个标准命令**:

| devtools 命令 | 包裹的现有能力 | 纯度 | 说明 |
|---|---|---|---|
| `regression-pack` | `regression_pack.main()` | 纯 | 确定性 gate，每次必跑。第一优先。 |
| `target-pack --report <json>` | `target_pack.summarize()` + `_print()` | 纯 | 只解析 artifact，**不**默认跑真 e2e。 |
| `diagnose --qid <q> [--e2e-result <run>]` | `diagnose_qid.main()` | 重 | 唯一保留重路径的命令；产物经 PX-1c 标准化。 |

**不进标准 CLI**（保持原脚本 + 手动授权）:
- `target_pack` 的真 e2e 运行路径（重、需 LLM profile、需显式授权——属 DEV_WORKFLOW 的 "E2E gate, 手动/授权"）。
- 一次性 audit 脚本（`*_audit.py` / `lco_audit.py` / `cq*` 等）——是历史调查工具，不是稳定入口。

**可选第 4 命令（PX-1c 衍生，纯）**: `report --diagnose-json <diagnose-<qid>.json>`
——对一个**已存在**的 diagnose rec 重新生成标准报告（summary.md + diagnosis.json +
recommended_next_action），完全不跑 ingest/LLM。这让"生成报告"和"跑诊断"解耦。

### Q2. 哪些输出字段是稳定 schema？

**稳定（可作为对外契约）**:

`path_summary`（DX-2a/2b/2c 已固化，有 `test_path_summary.py` 钉死）:
- `qid`
- `retrieval.{gold_hits_top_200, gold_hits_top_30}`
- `deterministic_layer.{fired[], refused[{helper,reason}], proofs_available[]}`
- `skill_route.{temporal_precision, open_domain_specific, list_ordering, structured_skill}`
- `closure_decision.committers{<name>:{proof_available, would_commit_on_abstain, would_overwrite_concrete}}`
- `closure_decision.suppressors{<name>:{detected, would_suppress_overcommit}}`
- `diagnosis.{layer, reason}` ← **最关键的对外字段**
- `final_answer.{answer, correct, judge_failed, answer_error, pure_abstain, helper_hints}`（仅当 `--e2e-result` 提供）

runner `per_query` record（`target_pack` 与 diagnose overlay 都依赖，已稳定）:
- `question_id`（注意: diagnose/target 都兼容 `qid` 别名）
- `correct` (bool)、`judge_failed` (bool)、`answer` (str, 截断 400)、`qtype`、`gold`
- `helper_hints.{savings, person_age, cashback, role_guard, temporal_endpoint, answer_pure_abstain}`

`target_pack.summarize` 产物（有 `test_target_pack.py`）:
- `rows[{qid,line,mode,present,correct,ok}]`、`required[]`、`observe[]`、
  `required_pass/required_total`、`observe_pass/observe_total`、`required_all_pass`

`diagnosis.layer` 枚举（DX-2c 收敛，DEV_WORKFLOW §4 已表格化）:
`pass` / `answer_or_judge_path` / `concrete_wrong_bypassed_committer` /
`proof_input_turn_missing` / `helper_refusal` / `retrieval_gap` /
`closure_ready` / `proof_ready` / `skill_route_gap` / `unknown`

### Q3. 哪些字段只是 debug/internal？

diagnose-<qid>.json 里**不应进对外报告**的 section（调查用，体积大、不稳定）:
- `retrieve_top_30_preview[]` — 逐条 content_preview，调试用，会随 retrieval 抖。
- `helper_signals{}` — 原始 helper 字符串输出（path_summary 已用 `helper_proofs` 取代它做投影）。
- `store_anchor_probe{}` — FACT 层正则扫描样本（dollar/age snippet），探查用。
- `self_anchor_probe{}` — store-scan 恢复 what-if，深挖用。
- `jab_what_if{}` — JAB veto 投影，特定调查用。
- `ingest_stats{}`、`question_date`、`structured_skill_section` 原始体 — 内部状态。
- `closure_view` 里 `proof.rendered` / `proof.sources[].quote` 等**全文证据**——
  对外报告应只引用 turn_id + 简短 value，不灌全文。

判据: **path_summary + diagnosis.layer + final_answer = 对外稳定层**；
其余 section 是 internal probe detail，报告可链接但默认折叠。

### Q4. 当前最小产品入口是什么？

今天事实上的"最小入口"是 3 条**手敲长路径命令**（DEV_WORKFLOW §1 的三 gate）:
```
~/.radiomind-bench-venv/bin/python bench/end_to_end/regression_pack.py
~/.radiomind-bench-venv/bin/python bench/end_to_end/target_pack.py --report <json>
~/.radiomind-bench-venv/bin/python bench/end_to_end/diagnose_qid.py --qid <q> [--e2e-result <run>]
```
痛点: 路径长、venv 前缀易忘、三个脚本风格各异、diagnose 输出要人脑解析。
**最小产品入口 = 把这三条收敛成一个统一 verb-based CLI**，先做 wrapper（不迁逻辑）。

---

## 4. 关键架构张力（PX-1b 落点决策）

任务建议的 `python -m radiomind.devtools` 有一个**真实的张力**，必须先定:

- 现有安装包入口是 **click** CLI: `pyproject` `[project.scripts] radiomind = "radiomind.cli.main:cli"`，
  `src/radiomind/cli/main.py`（846 行，click group）。
- 但 `regression_pack` / `target_pack` / `diagnose_qid` 在 `bench/end_to_end/`，
  **不在安装包内**，且彼此用 `sys.path.insert(0, parent)` + 同目录 import
  （`run_longmemeval_mem0`、`jab1_abstain_veto`）。
- 若做成 `src/radiomind/devtools.py`（随包安装），它 import `bench/` 会破层——
  安装后用户机器上根本没有 `bench/`。

**三个候选方案**:

| 方案 | 入口 | 优点 | 缺点 |
|---|---|---|---|
| A. `python -m bench.end_to_end.devtools` | bench 内新建薄 dispatcher | 与 bench 脚本同目录，import 零摩擦；纯 wrapper | 不是安装包命令，仍需仓库 checkout（但 bench 本来就只在仓库里用） |
| B. `radiomind dev <sub>` 子命令组（click） | 复用现有 click CLI | 统一到已有产品 CLI，一个入口 | click 命令需 import bench 模块——破包边界，要 `sys.path` 注入 bench，安装后不可用 |
| C. `python -m radiomind.devtools` | 安装包内新模块 | 符合任务字面建议 | 同 B 的破边界问题最严重 |

**推荐 A（`python -m bench.end_to_end.devtools` 或等价 `bench/devtools.py`）**，理由:
- 这些工具的受众是**仓库内的 dev**（跑 gate / 调 qid），不是装了 pip 包的终端用户。
  把它绑进安装包（B/C）是错配——终端用户既没有 dataset 也没有 bench 测试。
- A 与现有 bench import 习惯零摩擦，纯 wrapper 可在一个文件内完成，符合"先 wrapper 不迁逻辑"。
- 与现有产品 CLI（`radiomind` click）**职责分离**: `radiomind` 是给用户的运行时 CLI，
  `devtools` 是给开发者的诊断 CLI。两者不该混。

> 备注: 若后续确实想要 `radiomind dev ...` 的统一手感，可在 A 之上加一个**极薄的
> click 转发**（仅当 `bench/` 存在时注册子命令），但这是 PX-1b 之后的可选项，PX-1a 不决。

建议 devtools 命令形（PX-1b 草案，全部薄 wrapper）:
```
python -m bench.end_to_end.devtools regression-pack
python -m bench.end_to_end.devtools target-pack --report <artifact.json>
python -m bench.end_to_end.devtools diagnose --qid c18a7dc8 --e2e-result <run.json>
python -m bench.end_to_end.devtools report --diagnose-json diagnose-c18a7dc8.json   # PX-1c
```
内部直接 `import regression_pack / target_pack / diagnose_qid` 并调它们的 `main()`/纯函数，
**不复制任何逻辑**。venv 前缀问题可在 README 用 alias 解决，不进代码。

---

## 5. 标准 diagnosis report schema（PX-1c 草案）

目标: 每次失败都能**直接读懂**，而不是更聪明。三件产物 + 一个动作字段。

### 5.1 `diagnosis.json`（机器可读，稳定契约）
就是现有 `path_summary` 的**对外子集** + 一个新增 `recommended_next_action`:
```jsonc
{
  "qid": "c18a7dc8",
  "diagnosis": { "layer": "concrete_wrong_bypassed_committer", "reason": "..." },
  "retrieval": { "gold_hits_top_200": 3, "gold_hits_top_30": 1 },
  "deterministic_layer": { "fired": [...], "refused": [...], "proofs_available": [...] },
  "closure_decision": { "committers": {...}, "suppressors": {...} },
  "final_answer": { "correct": false, "judge_failed": false, "pure_abstain": false },
  "recommended_next_action": {
    "fix_family": "retrieval/turn-ranking audit",
    "do_not": "edit parser/regex",
    "pointer": "DEV_WORKFLOW §4 / §5"
  }
}
```
`recommended_next_action` 是 `diagnosis.layer` → 固定建议的**纯查表**（无 LLM），表见 5.4。

### 5.2 `summary.md`（人可读）
固定模板，从 diagnosis.json 渲染:
```text
# diagnose c18a7dc8 — WRONG (age-interval-committer line)

Layer:   concrete_wrong_bypassed_committer
Meaning: committer 证据就绪，但 answer-LLM 返回了一个具体的错误值（不是 abstain），
         所以 commit_on_abstain 从未触发。
Fix family: upstream hint-trust 或 suppressor 形态的 guard
Do not:     不要改 committer / 不要改 parser-regex

retrieval: gold 3/200, 1/30
closure:   age_interval would-commit=yes (on abstain); overwrite-concrete=no
e2e:       WRONG, concrete answer, not abstain
```

### 5.3 `path_summary` / `closure_view`（沿用现有 stdout 渲染）
`_print_path_summary` / `_print_closure_view` 已是稳定渲染，报告直接复用，不重写。

### 5.4 `layer → next_action` 查表（来自 DEV_WORKFLOW §4，固化为代码常量）

| layer | fix_family | do_not |
|---|---|---|
| `pass` | （无） | — |
| `answer_or_judge_path` | infra retry 或 answer-LLM trust/prompt | 不要当成逻辑 bug 去改 helper |
| `concrete_wrong_bypassed_committer` | upstream hint-trust / suppressor 形 guard | 不要改既有 committer |
| `proof_input_turn_missing` | retrieval/turn-ranking audit | 不要改 parser/regex |
| `helper_refusal` | 具名 helper 的 gate | 不要全局改 retrieval |
| `retrieval_gap` | retrieval breadth | 不要改 closure |
| `closure_ready` / `proof_ready` | 叠加一个 e2e result 看真实结果 | 不要假设 ready=pass |
| `skill_route_gap` / `unknown` | 改进诊断本身，补字段 | 不要改业务代码 |

这张表是**唯一新增的"知识"**，且它只是把 DEV_WORKFLOW §4 已写死的人类口径搬进
一个 `dict` 常量，不引入任何 runtime/scoring 判断。

---

## 6. 范围守卫与完成标准（对齐任务）

**PX-1a 不做**（本 log 已遵守）: 不改 mind.py / 不改 retrieval 排序 / 不新增 helper /
不跑 full n=100 / 不实现 CLI / 不动任何 scoring 逻辑。

**整条 PX-1 线完成标准**（供 PX-1b~1d 验收）:
- 一个命令跑 deterministic pack（wrap `regression_pack`）。
- 一个命令解析 target-pack artifact（wrap `target_pack --report`）。
- 一个命令对 qid 生成 human-readable diagnosis report（diagnose + PX-1c 报告）。
- report 明确给出 failure layer + next action。
- 不改任何 runtime scoring。
- `regression_pack` 全绿（PX-1b 会把 `test_devtools` / `test_report` 加进 PACK）。

---

## 7. 建议的下一步

进 **PX-1b**: 在 `bench/end_to_end/devtools.py` 写薄 dispatcher（方案 A），
3 个子命令全部 wrap 现有 `main()`/纯函数，零逻辑迁移。同步加
`tests/test_devtools.py`（确定性: 解析 argv → 路由到正确 callable，mock subprocess），
并把它挂进 `regression_pack` PACK 的 `harness:` 分类。

**待用户确认的唯一决策点**: PX-1b 入口形态 = 方案 A（`python -m bench...devtools`）
还是坚持任务字面的 `python -m radiomind.devtools`（方案 C，需破包边界）。
推荐 A。
