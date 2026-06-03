# PX-1b — devtools 薄 dispatcher（方案 A）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-03
> 前置: PX-1a audit（`2026-06-03-px1a-productization-devtools-audit-cc.md`）。
> 范围: 只做 wrapper + dispatch 测试。**不放进 `src/radiomind`，不改 runtime，
> 不跑 ingest/benchmark。** 报告 schema 留给 PX-1c。

---

## 1. 背景与目标

PX-1a 选定**方案 A**: 把三个仓库内 dev 命令统一到 `python -m bench.end_to_end.devtools`，
而不是塞进安装包 `radiomind.devtools`（会把 runtime 包和 bench 目录绑死）。

PX-1b 落地这个薄 dispatcher，统一三条入口:
```
python -m bench.end_to_end.devtools regression-pack
python -m bench.end_to_end.devtools target-pack --report path/to/artifact.json
python -m bench.end_to_end.devtools diagnose --qid c18a7dc8 --e2e-result run.json
```

## 2. 实现要点

### 新增 `bench/end_to_end/devtools.py`（薄 dispatcher）
- **零逻辑迁移**: 每个子命令只构造目标脚本已认识的 argv，再调它的 `main()`。
- **`plan(argv) -> Dispatch` 是纯函数**: argparse → `Dispatch{command, module, argv}`，
  **不 import 任何重模块、不跑任何 gate**。这是测试钉死的核心面，保证测试时
  绝不会意外触发 benchmark / ingest / LLM。
- **`run(argv)` 是唯一执行点**: 才 `importlib.import_module` 目标模块、临时改写
  `sys.argv` 调 `main()`、`finally` 还原 `sys.argv`。沿用 bench 脚本的 flat-import
  习惯（`sys.path.insert(0, 同目录)`）。
- **安全栏（关键设计）**: `target-pack` 子命令把 `--report` 设为 **required**。
  因此 devtools **永远无法**落入 `target_pack` 的重 e2e 真跑路径——无 `--report`
  时 argparse 直接 exit 2。真跑仍走 `bench/end_to_end/target_pack.py` 本体 + 手动授权。
- 命令映射:
  | devtools 命令 | 包裹 | 性质 |
  |---|---|---|
  | `regression-pack [--integration]` | `regression_pack.main()` | 纯、确定性 gate |
  | `target-pack --report <json>` | `target_pack.main()`（强制 report 模式） | 纯、只解析 artifact |
  | `diagnose --qid <q> [--e2e-result/--sandbox/--keep-sandbox/--out]` | `diagnose_qid.main()` | 重，仅转发 argv，不改逻辑 |

### 新增 `tests/test_devtools.py`（12 测试，确定性）
- 沿用项目惯例 `importlib.util.spec_from_file_location` 加载模块。
  **注意**: dataclass + `from __future__ import annotations`（PEP 563 stringized
  annotations）需要在 `exec_module` 前把模块注册进 `sys.modules`，否则 dataclass
  解析字符串注解时 `sys.modules.get("devtools")` 为 None → `AttributeError`。
  test loader 里加了 `sys.modules[spec.name] = m`（标准惯例，其它无 dataclass 的
  bench 测试没踩到这个坑）。
- 覆盖: 三 verb 的 module/argv 映射、`--integration`/`--e2e-result` 等转发、
  diagnose 全参拼接、`run()` 转发 argv 给 `main()` 并还原 `sys.argv`（mock 掉
  `import_module`，**不真跑**）、非零退出码透传。
- **安全栏测试**: `target-pack` 无 `--report` → `SystemExit`；`diagnose` 无 `--qid`
  → `SystemExit`；未知/空命令 → `SystemExit`。

### 修改 `bench/end_to_end/regression_pack.py`
- `PACK` 新增 `harness:devtools → tests/test_devtools.py`，挂进确定性 gate。

## 3. 修改文件
- 新增 `bench/end_to_end/devtools.py`
- 新增 `tests/test_devtools.py`
- 改 `bench/end_to_end/regression_pack.py`（仅加一条 PACK 项）
- 新增本 log
- **`src/` 零改动**（`git status` 确认）→ runtime 未触碰。

## 4. 遇到的问题
1. **dataclass + PEP 563 + spec 加载** 的 `AttributeError`（见上），修法: loader 注册 sys.modules。
2. 测试 mock `import_module` 的 lambda 用 `setdefault(...) or X` 误返回字符串
   （`setdefault` 返回真值 key）→ 改成显式函数。

## 5. 验证（完成标准对照）
- ✅ `python -m bench.end_to_end.devtools regression-pack` 能跑通。
- ✅ `target-pack --report <现有 artifact>` 正确解析并打印 summary（required 6/8 等，
  是该历史 artifact 本身的结果，非本次引入）。
- ✅ `diagnose` 参数正确拼接到 `diagnose_qid`（`--help` + plan 单测验证；未实跑重 LLM）。
- ✅ `target-pack`（无 `--report`）退出码 2——安全栏生效，绝不误跑 e2e。
- ✅ regression pack **全绿 17/17 类**（含新 `harness:devtools 12 passed`）。
- ✅ 无 runtime diff（`src/` 未动）。

## 6. 下一步
进 **PX-1c**: 标准 diagnosis report（`summary.md` / `diagnosis.json` /
`recommended_next_action`），并在 devtools 加纯命令
`report --diagnose-json <diagnose-<qid>.json>`（对已存在的 diagnose rec 重渲染，
不跑 ingest/LLM）。`layer → fix_family/do_not` 查表见 PX-1a log §5.4。
之后 PX-1d 更新 `03_DEV_WORKFLOW.md` + README 开发者段 + report parser 的确定性测试。
