# PX-1d — devtools 文档同步 + PX-1 收尾

> 作者: Claude Code (cc) ｜ 日期: 2026-06-03
> 前置: PX-1a (audit) / PX-1b (dispatcher) / PX-1c (report)。
> 范围: **纯文档**。不改 CLI 代码、不改 runtime、不跑 benchmark、不重生成 report artifact。

---

## 1. 目标
现在已有实际 CLI（4 命令）和 report 产物，做文档同步，让新用户/开发者能从文档直接找到并复制命令。

## 2. 改动（纯文档）

### `projectBasicInfo/03_DEV_WORKFLOW.md`（核心）
- §1 从 "三 gate" 改为 "一个 CLI 四命令"：写入统一入口
  `python -m bench.end_to_end.devtools <verb>`，列出 4 条复制即用命令，
  表格加 `report` 行（第四 gate）+ devtools verb 列 + underlying 列。
  - behaviour 类别计数 16 → **18**（PX-1b/1c 加了 `harness:devtools` + `diagnostic:report`）。
  - 明确推荐顺序：`regression-pack → target-pack --report / 真 target_pack.py → diagnose → report`。
  - 强调 devtools `target-pack` 因 `--report` required **永远无法触发重 e2e**，始终安全。
- §4 红点 triage 加 copy-paste 命令流（diagnose → report → 读 summary.md），
  并把 "target_pack red" 步骤改写为走 devtools diagnose + report。
- §6 "Where things live" 加 `devtools.py`（dispatcher）+ `diagnosis_report.py`（report）。

### `README.md` / `README_zh.md`（开发者入口）
- 在 "Validated performance" 段尾新增 `### Development & diagnostics` / `### 开发与诊断`：
  4 条命令 + 链接 `03_DEV_WORKFLOW.md`。简短，不写成内部手册。
- **未声称任何 current-main benchmark 分数**（沿用既有 benchmark-claim hygiene 口径：
  历史 artifact 用 `regression_pack`/`target_pack` 做 gate）。

### `projectBasicInfo/01_PROJECT_OVERVIEW.md`
- "Key paths" 加一行 `bench/end_to_end/devtools.py` 为 bench/dev workflow 统一入口。

### 本 log。

## 3. 验证（完成标准对照）
- ✅ 新用户能从 README（中英）"Development & diagnostics" 段找到 dev workflow 并跳转 03。
- ✅ 开发者能从 `03_DEV_WORKFLOW.md` §1 直接复制 4 条命令。
- ✅ §4 解释红点如何进入 `diagnose` → `report`（含 copy-paste 流）。
- ✅ 文档未声称 current-main benchmark 分数。
- ✅ **无代码 diff**：本轮只动 README.md / README_zh.md / 01 / 03 四个文档（git status 确认；
  status 里的 .py 全部来自 PX-1b/1c，本轮未改）。
- ✅ 文档命令与实际 CLI 一致（`devtools --help` 实测 4 verb 齐全）。

## 4. PX-1（Productization Workstream 1）整体收尾

| 步 | 产物 | 状态 |
|---|---|---|
| PX-1a | audit 设计 log（方案 A + report schema） | done |
| PX-1b | `devtools.py` 薄 dispatcher（regression-pack/target-pack --report/diagnose）+ `test_devtools.py` | done |
| PX-1c | `diagnosis_report.py`（diagnosis.json + summary.md，纯查表 next_action）+ `report` verb + `test_diagnosis_report.py` | done |
| PX-1d | 文档同步（03 / README / README_zh / 01） | done |

**最终入口**：`python -m bench.end_to_end.devtools {regression-pack|target-pack|diagnose|report}`
**纪律守住**：全程 `src/radiomind` 零改动、runtime/retrieval/helper/closure/scoring 未触碰、
regression pack 全绿（18 类，含新增 2 类）。这条线是纯 bench/dev tooling 产品化。

整条 PX-1 完成。后续若要更进一步（如把 devtools 接成 `radiomind dev ...` 统一手感），
是 PX-1a §4 备注里的可选项，需新立 scope，本线不含。
