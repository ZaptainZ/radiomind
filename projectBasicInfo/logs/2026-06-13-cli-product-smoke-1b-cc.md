# CLIProductSmoke-1b — 5 项纯 UX 修补（F1/F3/F4/F5/F6，F2 不碰）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: 1a smoke 的 6 个发现。用户裁决: 做 F1/F3/F4/F5/F6 纯 UX,不碰 L1 gate / domain
> 分类 / 训练门槛（F2 留给 SmallUserReadiness-1a）;不自动装 embedder;不跑 benchmark。

## 1. 改动
**F5 — `python -m radiomind`**: 新增 `src/radiomind/__main__.py` 委托 `cli.main:cli`。
`python -m radiomind --help` 可用。

**F1 — train refuse 可操作**: `DataGenReport` 加观测字段 `distinct_examples`（加性,
不碰门槛）;CLI `_render_train_gap(report, prepared)` 打印 habits/domains/examples 各
`have/need [ok|short]` + 下一步命令 + （prepare 已跑时）"DATA-VOLUME shortfall, not an
LLM/router failure"。两个 refuse 站点（data-only / full）统一改用它。门槛值不变。

**F3 — search 空 + 无 embedder 提示**: search 返空且 `mind._embedder is None` 时提示
"keyword(FTS) only,问句改关键词;pip install radiomind[embedding] 或配 retrieval
provider"。检索逻辑不动;关键词命中场景无提示。

**F4 — doctor PATH 不再误报**: 当前入口必然可用 → 恒 PASS。`which("radiomind")` 有 →
"on PATH — <path>";无 → "current entry works (<entry>); not on global PATH"。不再 WARN。

**F6 — LLM 后端 default-first + 标注**: router 新增 `backend_status()`（default 优先、
deprecated 末位、含 available/deprecated）;CLI `_render_backends()` 渲染
"dashscope [default], openrouter, openai [deprecated]"。doctor + status 共用。
`deprecated` 读可选 `[llm.<name>] deprecated = true`。

## 2. 验证（完成标准逐项命中）
- 单测 `tests/test_cli_product_ux.py`（11）: backend_status 排序、render 标签三态、
  train gap 三门槛 ok/short、prepared 文案、distinct_examples 默认、`python -m` --help
  子进程、F3/F4 源码守卫。pack 新增 `cli:product-ux` → **31 类全绿**;全量 **1011 passed**。
- **re-smoke（空 home + dashscope config）**: F5 ✓；F1 ✓（"habits 1/5/domains 1/2/
  examples 11/30 [short]" + data-volume 提示 + next step）；F4 ✓（PASS 显示 current
  entry）；F6 ✓（dashscope [default] 首、openai [deprecated] 末）。
- **F3 双态验证**: dashscope-config home 下 `mind._embedder` = DashScopeEmbedder（**非
  None**,config 有 key 时远程 embedder 自动激活）→ 提示**正确不触发**（确实有 embedder）;
  另起 ollama-only/无 key home → embedder=None → 提示**正确触发**。**澄清 1a 误判**: 1a
  说"无 embedder → FTS"不准确——dashscope key 在时有远程 embedder,自然问句返空是
  小 store 检索质量问题,非"缺 embedder";F3 只在真无 embedder 时提示,行为正确保守。

## 3. live config 同步（F6 deprecated 标记,行锚定 + 备份）
`[llm.openai]` 段加 `deprecated = true`（备份 config.toml.bak-<ts>;用 header+base_url
双行 anchor + count==1 断言,杜绝上次 str.replace 咬注释的复发）。**编辑后立即复跑全量
1011 passed + tomllib 校验**（吸取昨日 Fix D 教训: config 改完先复跑再宣称通过）。

## 4. 不做 / 守住
F2（L1 gate 激进 + domain 稀疏）未碰——属架构语义,留 SmallUserReadiness-1a。不降门槛、
不自动装 embedder、不改检索逻辑、未跑 benchmark。

## 5. 完成标准对照
- 小数据训练失败可看懂差什么/下一步 ✓（F1）
- 无 embedder search 空不再像系统坏 ✓（F3,真无 embedder 时）
- doctor 不对 venv 正常入口误报 ✓（F4）
- `python -m radiomind --help` 可用 ✓（F5）
- pack + CLI/doctor/search 测试全绿 ✓（1011）
- re-smoke 确认除 F2 外 5 点改善 ✓
