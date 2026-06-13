# RadioHeaderMind-1b — RadioHeader backend contract 审计（只读，不实现）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 范围: 只读审计 RadioHeader 侧当前 RadioMind delegation。不实现、不改 RadioMind repo、
> 不做 memory migration、不删 native fallback。审计目标 = 已部署 CLI `~/bin/radioheader`
> （bash v2.0.0）+ 数据库 `~/.claude/radioheader/`。注: RadioHeader 源码仓未本地签出,
> 审计的是已部署 CLI（可读 bash,非编译产物）。

## 1. 现状盘点（实测自 ~/bin/radioheader）
- **CLI**: 单 bash 脚本 v2.0.0;子命令含 search / consolidate / init / mcp-server / community /
  rh 桥接等。
- **radiomind delegation（与准备文档完全一致）**:
  - `radiomind_available()` = `command -v radiomind`（行 59）。
  - **search**（行 695-703）: 可用且 `use_fts!=no` → `radiomind rh-search <pattern> [--field]`,
    成功 return 0;失败 `warn` → native FTS5（`fts-search.py` + `search.db`）。
  - **consolidate**（行 3836-3845）: 可用 → `radiomind rh-consolidate [--dry-run]`,成功 return 0;
    失败 `warn` → native `attn-consolidate.py`。
  - **suggestion**: radiomind 缺失时提示安装（14 天 cooldown,`.radiomind-suggested`),纯提示无副作用。
- **hooks（模板 `templates/project`）**: SessionStart → `load-project-rules.sh`;Stop → echo
  "Echo reminder"（**纯文字提醒,不执行 consolidate**）。`init` 拷贝 settings.json/hooks.json,
  已存在则跳过。
- **MCP**: RadioHeader 有**自己的** `mcp-server`（cmd_mcp_server,装在 CLI 旁),独立于 RadioMind MCP。
- **Echo / rules / 源文件**: 写 `topics/` `shortwave/` `project-registry` 等本地文件,**RadioHeader
  原生,未 delegate 给 radiomind**。
- `.consolidate-counter`（值"2"）: consolidate 运行计数,**无自动触发逻辑**（grep 确认 CLI 无
  counter-based auto-consolidate）。

## 2. 验证: delegation 与描述一致 ✓
准备文档描述（CLI/file compatibility,非正式 backend abstraction;仅 search/consolidate 两路
delegate + native fallback）**逐条验证属实**。无隐藏的 radiomind 写路径;Echo writes 仍原生。

## 3. 关键授权发现（对照 PersonalOnboarding-1c 原则）
- **RadioHeader 的 RadioMind-backed 副作用全是前台显式触发**: `radioheader search`/
  `radioheader consolidate` 都是用户/AI 显式命令,**无 hook/counter 自动触发 consolidate**。
- → **天然符合 1c "只门控后台自动副作用"原则**: RadioHeader 当前不存在"装上就自动 LLM/
  mutation"的问题（与 Hermes provider 1a 的隐患相反）。consolidate 的授权 = 隐含于"用户主动
  敲 consolidate"。
- **副作用分级**:
  | delegation | LLM | 写 store | 改 digest | 授权现状 |
  |---|---|---|---|---|
  | search→rh-search | — | — | — | 读,无需授权 |
  | consolidate→rh-consolidate | ✅(dream) | ✅ | ✅ | 前台显式,合规 |

## 4. 判定: 当前 CLI delegation 是否足够
**对当前产品目标（RadioHeader owns rules/hooks/Echo/源文件;RadioMind 作可选 read+consolidate
backend）—— CLI delegation 基本足够,formal backend abstraction 非必需,但有一处增值缺口。**
- 足够的理由: 简单、有干净 fallback、RadioHeader 保留所有 ownership、副作用前台合规。
- 唯一增值缺口: **RadioHeader 的 SessionStart 注入的是静态 `context-digest.md`,不拉 RadioMind
  的 live digest**（RadioMind 有 `digest`/`get_context_digest`,未被 RadioHeader 消费）。若要让
  编程 Agent 用上 RadioMind 的实时 digest,CLI 当前路径没有;这是 backend contract 唯一能带来
  实质新能力的点。

## 5. 最小 v1 backend 接口草案（设计,不实现;仅当决定要 abstraction 才用）
read-oriented 优先,不迁 Echo writes,保留 native fallback:
```
MemoryBackend.search(query, *, field=None, scope=None) -> list[hit]      # 现 rh-search
MemoryBackend.health() -> {available, version, store_stats}              # 现 radiomind --version 的结构化版
MemoryBackend.context_digest(*, token_budget=250) -> str                 # 新增价值点(§4 缺口)
MemoryBackend.consolidate(*, dry_run=False) -> {merged, pruned, ...}     # 现 rh-consolidate
```
- v1 **不纳入**: Echo write 迁移、habit/train、memory CRUD、delete、订阅、向量托管。
- 实现形态可仍是 subprocess（保持 CLI 兼容）或薄 Python import,RadioHeader 自选;**native
  fallback 不删**。

## 6. 授权边界（写给未来实现,务必遵守）
- search / health / context_digest = read-only,无需授权。
- **consolidate = LLM + mutation + digest rewrite,需授权**。当前因"仅前台显式"而合规;
  **若未来任何 hook/counter/backend 自动触发 consolidate,必须 deny-by-default + 显式授权**
  （对齐 PersonalOnboarding-1c：门控后台自动副作用，前台显式调用不门控）。
- RadioHeader 必须继续 **owning: rules / hooks / Echo writes / 源文件 / native fallback**;
  RadioMind 只是 **optional backend,非 replacement**。

## 7. 结论 + 下一步
- **当前 CLI delegation 足够支撑 v1 产品目标,不急于做 formal abstraction。**
- 若要推进 abstraction,理由应是 **context_digest live 注入**（唯一实质增值）+ 减少 subprocess
  脆弱性,而非"delegation 不够"。
- 下一步候选（**均在 RadioHeader repo 侧,需在那边立项,不在 RadioMind 做**）:
  RadioHeaderMind-1c = 实现 §5 read-oriented 接口（先 search/health/context_digest,consolidate
  保持现状）+ 保留 native fallback + consolidate 自动触发的授权 gate（若引入）。
- 本轮零代码改动;未发现需修的明显文档错误（delegation 与准备文档一致）。

## 8. 不做 / 守住
未改 RadioMind repo、未改 `~/bin/radioheader`、未做 memory migration、未删 native fallback、
未做订阅/向量。仅审计 + 设计草案。
