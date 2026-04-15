# P1 修复执行记录（v0.2 路线图第一阶段）

日期：2026-04-15
执行：Claude Code
上游计划：`2026-04-15-system-audit-and-roadmap-cc.md`

## 背景

系统审计在 P0/P1/P2 找出若干阻塞点（向量检索未读、验证闭环缺失、多用户未通、LoRA 未经评估等）。本次任务要求按顺序修完 P1 五个子项，且「测试必须沙箱化，不要影响我本机的真实记忆」。

## P1 子项与结果

### P1.1 向量检索全链路（已在之前会话完成，沿用）
- `MemoryStore.search_vector`（numpy 余弦）
- `PyramidSearch` 接入 embedder，vector → FTS → LIKE，RRF 融合
- `radiomind embed-backfill` 命令
- `Simple.search` 在返回结果里暴露 `retrieval_method`

### P1.2 习惯验证闭环
- `HabitStore` 引入 `MIN_CONFIDENCE=0.7` / `PROMOTION_HITS=3` / `ARCHIVE_AGE_DAYS=14`
- `add_habit` 低置信度直接返回 None；重复 description 去重
- `record_hit` 累计命中后自动从 candidate → confirmed
- `reject_habit` 两次拒绝 → archived
- `prune_stale` 定期归档 14 天零命中的候选
- `query` 跳过 archived，并回写 hit
- refinement/chat/dream/step：向 add_habit 透传 confidence 并过滤被拒绝的 insight
- MCP：`radiomind_reject_habit` 工具及 handler
- 顺带修复：`Config.load()` 现在读取 `RADIOMIND_HOME` 环境变量（此前测试脚本泄漏污染了 `~/.radiomind`，本次清理后用沙箱验证）

### P1.3 多用户贯通 + Memory CRUD
- schema v3：`memories` 新增 `updated_at/user_id/agent_id/session_id` 列，新建 `memory_history` 审计表
- 索引覆盖新列
- `RadioMind.ingest` 接收 `user_id/agent_id/session_id` 参数
- `RadioMind.search` 支持 scope 过滤
- 新 CRUD：`get_memory / update_memory / delete_memory / delete_all_memories / memory_history / list_memories`
- `SimpleRadioMind` 暴露 `get / update / delete / delete_all / history / list`
- `Memory` 协议类新增 id / user_id / agent_id / session_id / created_at / updated_at
- `delete_all` 拒绝无 scope 的调用，避免误全删
- 搜索带 scope 时跳过 habits（habits 视为全局）

### P1.4 doctor + setup 备份 + plugin.json
- `radiomind doctor`：检查 home / schema / embedder / LLM / 平台 / CC 集成 / CLI 路径；PASS/WARN/FAIL；FAIL 退出码 1
- `hooks.setup._backup_file` 在写 `settings.json / hooks.json / mcp.json` 前打时间戳备份（`*.radiomind-bak.YYYYMMDD-HHMMSS`）
- `.claude-plugin/plugin.json` 补完：mcpServers、postInstall，版本升到 0.2.0

### P1.5 LoCoMo-lite benchmark
- `bench/locomo_lite/`：60 条陈述 × 50 条查询的合成数据集
- `run.py` 输出 R@5 / R@10 + 每查询明细；`--save` 写 JSON
- R@5 跌破 0.3 非零退出，可做 CI 回归门禁
- 顺带修复：CJK 查询时 `PyramidSearch` 始终补充 LIKE（unicode61 tokenizer 对 CJK 只按标点切分，中间子串会漏），失配时再用字符二元组 LIKE
- Baseline（无 embedder）：R@5 = 0.71，R@10 = 0.73，延迟 < 1ms

## 沙箱隔离
所有测试都走 `RADIOMIND_HOME=/tmp/rm-sandbox-*`，跑完即清。`~/.radiomind` 在 P1.2 过程中被上一轮脚本意外写入，已清空 habits.json；`Config.load()` 修复后后续测试均未再污染。

## 提交清单
- `P1.2: habit validation loop + sandbox isolation`
- `P1.3: multi-user scope + Memory CRUD`
- `P1.4: doctor + setup backups + plugin.json manifest`
- `P1.5: LoCoMo-lite benchmark + CJK n-gram LIKE supplement`

## 下一步（P2 起步）
P2 是 LoRA「做对」——用户明确要求 LoRA 必须作为硬任务完成且调好：
1. 训练数据质量：从 habits + confirmed L3 + 高频 L2 抽取，严格去重
2. 流程：early stopping / eval set / 过拟合检测
3. 评估：在 LoCoMo-lite 上跑 before/after LoRA A/B
4. 部署：LoRA → GGUF 通过 radiomind deploy 落地 Ollama

预计分三次以上提交。
