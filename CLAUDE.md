# CLAUDE.md — RadioMind

## Project Info
- 定位: 独立的仿生记忆-思考核心，为 AI Agent 提供可插拔的深层记忆能力
- 关系: RadioHeader / RadioHand 的默认记忆模块，也可接入 Hermes/OpenClaw 等
- Tech stack: Rust + Python + SQLite + HDC + MLX (架构设计完成，v0.1 待启动)
- Terminology:
  - L1 记忆草稿: 对话历史的注意力门控层
  - L2 记忆笔记: 3D 金字塔结构化存储 (domain × time × level)
  - L3 习惯记忆: HDC 超维编码 + LoRA 深层内化
  - L4 外挂知识: Shortwave 库 ("让记忆去读书")
  - "聊天"炼化: 三体博弈 (守护者/探索者/精简者) 创造新洞察
  - "做梦"炼化: 神游 Agent 修剪 + 自由联想
  - Meta 双侧写: 用户侧写 + 系统自画像 (元认知)
- Runtime notes:
  - `.claude/rules/*.md` contains the project's operating rules
  - Use this file as the routing index; do not read every project document by default
  - If architecture or key paths change, update `projectBasicInfo/01_PROJECT_OVERVIEW.md`
  - If significant work is completed, write a log in `projectBasicInfo/logs/`

## Document Index (consult as needed, don't read everything)
| Document | When Needed |
|----------|------------|
| `projectBasicInfo/00_AGENT_RULES.md` | Unsure about operation guidelines |
| `projectBasicInfo/01_PROJECT_OVERVIEW.md` | Unfamiliar with project structure |
| `projectBasicInfo/logs/` | Need implementation history or need to record this task |
