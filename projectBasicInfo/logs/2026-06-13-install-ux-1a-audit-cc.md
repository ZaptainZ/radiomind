# InstallUX-1a — 安装/首次运行体验审计（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 范围: 新用户视角盘点安装 + 首次运行,只读,不改代码。

## 1. 打包结构 — 健康,无阻断
- `[tool.setuptools.packages.find] where = ["src"]` → **仅 `src/radiomind` 进安装包**;
  bench/ tests/ devtools **不会进用户环境** ✓（用户裁决关注点之一,确认安全）。
- entry point `radiomind = radiomind.cli.main:cli` ✓;`src/radiomind/__main__.py`（1b F5）
  在 src 内 → **`python -m radiomind` 发布后仍可用** ✓。
- **src 无 bundled 非 .py 数据文件依赖**（grep 确认: 所有 open() 是 DB/socket/用户文件;
  config 读用户 home;dataset_errata.json 等只在 bench）→ **无需 package-data,安装不会
  缺文件** ✓。
- deps 最小（numpy/click/tomli）+ 7 个 optional extras;requires-python>=3.10 ✓。

## 2. 阻断级问题: 无
安装路径结构上是通的。`pip install` / `uv pip install` / venv 三法 README 都有且准确。

## 3. 误导级问题（doc 滞后于已实现能力）
- **M1 多 provider 配置未文档化**: LLMRouter-1b 已支持任意 `[llm.<name>]`（dashscope/
  openrouter…）profile,但 quickstart 手动配置示例仍只给 `[llm.openai]` 且
  `default_backend = "openai"`——**正是本机踩过的死端点 footgun 形态**。想用 DashScope 的
  用户会照抄 openai 段。应给 `[llm.dashscope]` 示例 + 标注 default 选择。
- **M2 "zero config" 需限定**: README/quickstart 多处"zero config / no config file needed"。
  实际: 走**环境变量**（DASHSCOPE_API_KEY 等）才是真零配置（quickstart 有写,优先级正确);
  但 `radiomind init` **不生成 config.toml**（实测 fresh init 只建 data/,无 config）→ 想用
  config.toml 的用户没有模板可改、也无提示。建议把 env-var 作为新用户头条路径。
- **M3 `python -m radiomind` 未文档化**: 1b F5 已支持,doctor F4 也引用它,但 README/
  quickstart 的 CLI 段只用裸 `radiomind`。脚本不在 PATH 时用户无从知道 fallback。

## 4. 可优化级
- **O1 无端到端"冷启动到 LoRA"文档路径**: 2a 证明 init→ingest→train --prepare-habits →
  FULL/narrow adapter 可走通,但 quickstart 不含该序列;用户不知道顺序。建议加一段,
  并注明 full vs narrow 与数据量预期。
- **O2 init 不 scaffold config**: 可选——`init` 写一份带注释的 config.toml 模板会让配置
  路径可发现（当前 `radiomind config <key> <value>` 能写但无人知道）。
- **O3 extras `all` 漏 server**: `all = [ollama,openai,vec,embedding,train]` 不含 server;
  与 extras 列表轻微不一致（无害,文档/打包小修）。
- **O4 quickstart `ingest /dev/stdin`** 示例脆弱;且"5 minutes to first memory"标题对
  LoRA 训练路径设错预期（训练非 5 分钟、需 MLX + 足够数据）。

## 5. "新用户 15 分钟路径"是否成立
- **到"第一条记忆 + 搜索": 成立** ✓（install → connect/add/search,文档准确,快）。
- **到"训练出 LoRA adapter": 不成立（但合理）**: 序列未文档化(O1) + 需 MLX 安装 + 足够
  数据 + 非分钟级。LoRA 是 opt-in/进阶,可接受——但 doc 应明确设此预期,别让"5 分钟"
  暗示训练也快。

## 6. 最小修复建议（本轮不改代码,留 InstallUX-1b)
按性价比:
1. **doc M1+M3+O1（纯文档,零风险,最高价值）**: quickstart/README 加 `[llm.dashscope]`
   多 profile 示例 + 标死 openai、加 `python -m radiomind` fallback、加"冷启动到 LoRA"
   序列（引 2a，注 full/narrow）。
2. **doc M2**: 把 env-var 设为新用户头条,"zero config"限定为"设一个 API key 环境变量"。
3. **code O2（小）**: `radiomind init` 可选 scaffold 注释版 config.toml（发现性）。
4. **O3/O4（琐碎）**: extras all 补 server;quickstart 标题/示例措辞。

## 7. 结论
**安装/打包层无阻断,结构干净**（src-only 打包、entry point、`python -m`、无 package-data
缺失）。短板全在**文档滞后于 1b/1e/2a 已实现的能力**（多 provider、`python -m`、冷启动到
LoRA）。建议开 **InstallUX-1b 纯文档修复**（M1/M2/M3/O1），可选带一个 `init` config
scaffold（O2）。不动安装机制本身——它已就绪。
