# RadioHeaderMind-1a — 三入口产品路由（纯文档定位）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: Codex 的 `04_PRODUCT_ONBOARDING_IMPLEMENTATION.md` 产品决策。
> 范围: 纯文档/定位。不改 runtime、不做订阅、不做向量托管、不动 RadioHeader repo。

## 1. 改动（4 个文档）
按 04 文档 §3.2 RadioHeaderMind-1a + §6 "First task to give CC":
- **README.md / README_zh.md**: 在 intro 后、首个内容 section 前新增 **"Which entry should
  I use? / 我该用哪个入口"** 路由表:
  | 用户类型 | 安装/使用 | RadioMind 角色 |
  |---|---|---|
  | 编程 Agent（CC/Codex/Cursor/Windsurf） | **RadioHeader（推荐）** | RadioHeader 管行为契约,RadioMind 做记忆后端;不建议自接裸 RadioMind |
  | 个人 Agent（Hermes/OpenClaw/RadioHand） | RadioMind memory provider | 长期个人记忆引擎 |
  | 硬核用户（Python/CLI/MCP） | RadioMind 原生 API | 直接控制 store/search/refine/dream/train/deploy |
  并注明本 README 其余部分讲引擎（个人 Agent + 硬核路径），指向 04 实施方案。
- **docs/integration.md**: 顶部 callout"编程 Agent 用户请先装 RadioHeader,下面 5 法是
  个人 Agent + 硬核直接接引擎"。
- **docs/quickstart.md**: 顶部一行"编程 Agent? 改装 RadioHeader"指引,保持四处口径一致。

## 2. 验收对照（04 §3.2）
- 新用户能判断装 RadioHeader 还是 RadioMind ✓（README 顶部路由表）。
- 编程 Agent 用户不再被首要导向裸 RadioMind ✓（四个文档入口全部前置 RadioHeader 指引）。
- 现有 quickstart 对硬核用户仍可用 ✓（仅加顶部指引,正文未改）。

## 3. 不做 / 守住
零 runtime 改动。未做通用 LLM 订阅、未做向量/重排托管（04 §1.2/§1.3 延后）。未改
RadioHeader repo（RadioHeaderMind-1b 在那边做）。`git diff --check` 干净。

## 4. 下一步（04 给 CC 的顺序,待用户逐条立项）
PersonalOnboarding-1a（只读: Hermes/MCP 集成盘点,宿主 LLM 复用点,导入授权点）→
PowerUserOnboarding-1a（CLI/API/MCP 命令图 vs 文档,gap 表）→ RadioHeaderMind-1b
（RadioHeader repo: backend contract,不迁数据不改 RadioMind）。ManagedRetrieval / 订阅
显式延后（04 §5,隐私问题已记）。
