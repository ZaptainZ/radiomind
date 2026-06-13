# PowerUserOnboarding-1b — 硬核用户文档修补（纯文档）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 性质: 纯文档。不改 runtime/MCP server,不跑 benchmark,不接订阅/向量,不碰 RadioHeader repo。
> 依据: `logs/2026-06-13-poweruser-onboarding-1a-audit-cc.md`。

## 1. 改动（README.md / README_zh.md / docs/api-reference.md）
- **MCP 计数修正**: README "9 MCP tools" / README_zh "9 个 MCP 工具" / api-reference
  "8 tools" → 全部改为**能力分类 + 与代码对齐的 17（注 as of 2026-06-13）**,不再把易过时的
  裸计数当主卖点。
- **api-reference MCP 段重写为完整 17 tool 分类表**: Retrieval/read（7）/ Memory write（5）/
  Refinement（3）/ Habits→host（2),每行 tool / purpose / LLM? / writes?。并加
  **前台 vs 后台**说明（MCP tool 是显式调用,不走 provider 后台授权门控;train/deploy CLI-only
  不在 MCP）。
- **api-reference 新增 CLI command reference**: 21 命令单页表（command / purpose / 副作用类 /
  needs LLM），副作用类沿用 1a（read-only / writes-local / writes-config-host / calls-LLM-
  embedding / trains-deploys / starts-server）。
- **README "Use" 补 Python 高级路径**: 显式展示 `mind.advanced.trigger_dream()/train()`,
  并说明 dream/train/deploy 在 `.advanced` 或 CLI——硬核用户不再以为 Python 只能 CRUD/search。

## 2. 完成标准对照
- README/README_zh 不再低报 MCP 能力 ✓（改 17 + 能力分类）
- api-reference 有完整 MCP 能力分类 ✓（17 tool 四组表）
- 硬核用户能找到 CLI 命令参考 ✓（api-reference 新增 21 命令表）
- Python 高级能力路径不再隐藏 ✓（README .advanced dream/train 示例）
- 前台显式调用 vs 后台自动副作用边界写清 ✓（api-reference MCP 段 callout）

## 3. 验证
- 全仓 grep `8 tools`/`9 MCP`/`9 个 MCP`/`8 个 tools` → **0 残留**。
- `git diff --check` 干净;仅 3 个 .md 改动,零代码。
- 链接均指向已存在文件（api-reference.md / integration.md）。

## 4. 不做 / 守住
未改 MCP server、未新增 tool、未做 radiomind onboard、未接订阅/向量、未碰 RadioHeader repo。
计数对齐用"as of 2026-06-13 + 能力分类"避免再次过时。

## 5. 三入口公开文档对齐 — 收口
- 编程 Agent → RadioHeader（RadioHeaderMind-1a 路由表）
- 个人 Agent → RadioMind provider（PersonalOnboarding 1a→1b→1c 安全默认 + 契约）
- 硬核用户 → CLI/Python/MCP（PowerUserOnboarding 1a 审计 → 1b 文档补齐）
三条入口现都有公开可读、与代码一致的路径。下一步候选（不在本轮）: `radiomind onboard`
交互命令 / ManagedRetrieval 订阅设计 / RadioHeaderMind-1b（RadioHeader repo backend contract）。
