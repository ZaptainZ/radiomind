# 2026-04-15 系统大检查 + 修复路线

## 背景

v0.1 功能完成、发布 GitHub 后，并行派出 4 个审查 agent 对照 Mem0 / mempalace / Zep / Letta 全面审查。发现"形似神不至"：架构图漂亮、模块齐全，但关键链路实际是断的。

## 核心发现（P0 阻塞性）

| # | 问题 | 来源 |
|---|------|------|
| 1 | 向量搜索只写不读，embedding 占死磁盘 | 存储审查 |
| 2 | `user_id` 是假 API，声明未贯通 | API 审查 |
| 3 | Memory 无 id/timestamps，Simple API 无 CRUD | API 审查 |
| 4 | 候选 insight 无验证闭环，confirm() 是孤儿方法 | 炼化审查 |
| 5 | 无任何召回率 benchmark | 存储审查 |
| 6 | plugin.json 不完整，README 承诺的 `claude plugin add` 装不上 | UX 审查 |
| 7 | setup 覆写 settings.json 不备份 | UX 审查 |

## LoRA 决策

审查 agent 建议砍掉 LoRA（demo 过拟合、价值存疑）。用户明确反对：LoRA 是 RadioMind 的长期差异化护城河，必须做对而不是砍。

决定：LoRA 作为阶段 2 的硬要求——数据量门槛、多样化训练样本、早停、质量评估、部署闭环全部到位。

## 修复路线 v2（3-4 周）

### 阶段 1：断链修复（5-7 天）
- 1.1 向量搜索全链路 + RRF 融合 + 降级链
- 1.2 验证闭环（hit_count/reject/TTL/promotion）
- 1.3 多用户贯通 + Memory CRUD
- 1.4 radiomind doctor + setup 备份 + plugin.json 完整
- 1.5 LoCoMo benchmark 基线

里程碑：v0.2.0-beta

### 阶段 2：LoRA 做对（3-5 天，硬要求）
- 2.1 训练数据质量（数据量门槛、多样化、验证集独立）
- 2.2 训练流程优化（早停、LR 调度、配置分级）
- 2.3 训练后评估（A/B 对比、habit recall、拒绝率）
- 2.4 部署闭环（GGUF 转换、热切换、版本管理）
- 2.5 触发与文档

里程碑：v0.2.0

### 阶段 3：质量打磨（1-2 周）
- 3.1 炼化质量（Prompt 重写、异构模型、session 持久化、自动触发）
- 3.2 KG entity resolution
- 3.3 补齐 MCP 工具（9→16）
- 3.4 async + batch API
- 3.5 Schema migration 框架
- 3.6 UX 细节

里程碑：v0.3.0

## 测试策略

**沙箱隔离**：所有修复测试使用 `RADIOMIND_HOME=/tmp/radiomind-sandbox-$(date +%s)`，不污染本机 `~/.radiomind/` 的真实记忆数据。

## 启动顺序

第一周三件事：
1. 向量搜索链路接通（2 天）
2. 验证闭环（1 天）
3. user_id 贯通 + Memory CRUD（1.5 天）
