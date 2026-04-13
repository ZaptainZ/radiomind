# 2026-04-13 RadioMind 架构设计

## 背景

RadioMind 项目从零开始，经过两天多轮讨论，完成了从愿景到架构的完整设计。

## 讨论演进

1. **起点**: 探讨将 RadioHeader 扩展为通用 Agent 框架 (RadioMind)
2. **调研**: 对标 Hermes Agent (47k stars)、OpenClaw、mempalace，分析竞品格局
3. **定位调整**: 从"Agent 框架"→"个人对话 Agent"→"可插拔记忆模块"
4. **仿生方向**: 引入神经科学类比（海马体/新皮层/睡眠巩固/突触/LoRA）
5. **四层记忆**: 草稿→笔记→习惯→外挂，对应大脑的工作记忆→海马体→新皮层→文化记忆
6. **炼化机制**: "聊天"(三体博弈) + "做梦"(神游修剪)
7. **技术验证**: Mac 上 MLX LoRA 可行 (0.6B ~5分钟, 3B ~15-30分钟)
8. **升维存储**: 金字塔(L2, 注意力式检索) + HDC(L3, 超维压缩)
9. **元认知**: 双侧写（用户 + 系统自身），一切不写死

## 最终产出

- `projectBasicInfo/01_PROJECT_OVERVIEW.md` v3 完整重写（~450 行）
- `CLAUDE.md` 更新定位和术语表
- 产品关系确认: RadioMind(记忆核心) → RadioHeader(编程适配) / RadioHand(Agent框架)

## 关键决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 产品定位 | 独立记忆核心，非 Agent 框架 | Agent 框架竞争激烈，记忆炼化无人做 |
| L2 技术 | 3D 金字塔 (SQLite) | 类注意力机制，成熟可靠 |
| L3 技术 | HDC + LoRA | HDC 简洁零依赖，LoRA 深层内化 |
| 炼化角色 | 三体(3 Agent)而非双体 | 三方制衡更稳健 (ICLR 2025 验证) |
| Mac 训练 | MLX (非 QLoRA/bitsandbytes) | bitsandbytes 不支持 Apple Silicon |
| 配置原则 | 一切不写死 | 用户可能更改 LLM/后端/通道 |

## 待决问题

- 领域预设、隐私分级、开源许可、v0.1 用 Python 还是 Rust
