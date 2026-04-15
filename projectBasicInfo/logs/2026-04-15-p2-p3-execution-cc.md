# P2 + P3 修复执行记录（v0.2 路线图第二、三阶段）

日期：2026-04-15
执行：Claude Code
上游：`2026-04-15-system-audit-and-roadmap-cc.md`, `2026-04-15-p1-execution-cc.md`

## P2 LoRA「做对」

### P2.1 数据质量（提交 4f22bbc）
审计最重的一个坑：旧 `data_gen` 把 train 直接复制为 valid，任何 loss 下降都是记忆化。另外每个 habit 的样本都是同样的全局聚合答案。

修复：
- 真正的 80/20 随机拆分，固定 seed=20260415，写 `valid.jsonl` 作为同级文件，再也不复制
- 严格按归一化 Q+A 指纹去重
- 每个 habit 生成最多 `MAX_EXAMPLES_PER_HABIT=6` 个不同锚点问题
- `_ok_answer` 过滤「还在了解中 / 暂无 / 还在积累中」这种无信息回答，避免把空壳当事实训下去
- Quality gate：`MIN_DISTINCT_EXAMPLES=30`、`MIN_HABITS=5`、`MIN_DOMAINS=2` 不达标直接 refuse，并通过 `DataGenReport` 告诉调用方原因
- `lora.py`：最少 30 样本才训，`iters_per_example_cap=10×` 防止小数据 runaway，LoRA dropout 0.0 → 0.05

### P2.2 A/B 评估（提交 1aa56f3）
`bench/lora_ab/eval.py`：
- 在 LoCoMo-lite 50 条查询上跑 base vs LoRA（两个 Ollama 模型）
- 同样的 RAG 上下文，两侧公平比较
- 用 gold-statement token overlap 打分（CJK 按字、ASCII 按词），无需 LLM judge
- 输出 wins/losses/ties、delta、per-query 明细
- 若 LoRA 平均分比 base 低 > 0.05 → 退出码 1（CI 回归门禁）
- 没有 LoRA 时退化为「base + RAG」单侧冒烟，Ollama 不可用时返回明确错误

### P2.3 部署修复（提交 1aa56f3）
旧 `export_to_ollama` 用 `mlx_lm.convert` 去产 GGUF，但 MLX 不输出 Ollama ADAPTER 所需的 GGUF-LoRA 格式，这条路径本来就走不通。改为正确的三段流水线：
1. `mlx_lm.fuse` 把 adapter 合并到 base → fused 目录
2. llama.cpp 的 `convert_hf_to_gguf.py` 把 fused 模型量化转 GGUF（通过 `$LLAMA_CPP_CONVERT` 或 `--llama-cpp-convert` 指定）
3. `FROM {gguf}` 写 Modelfile，把 adapter 烘进新 base
4. `ollama create` 注册

工具缺失时给出具体 fix 提示，不会跑一条 broken 命令。

## P3 质量打磨

选了三块影响最实际的：

### 会话持久化（提交 42a50b7）
`StepRefiner` 的 sessions 之前只在内存里——host AI 驱动的「三体博弈」在 prepare → guardian → explorer → reducer → synthesize 任意环节进程挂掉就全丢。

改成：每次 `step()` 结束自动写 `{home}/data/refine_sessions.json`，新进程加载时读回。验证：两个 RadioMind 实例一前一后调用 prepare / guardian，session 无缝衔接。

### 新增 6 个 CRUD MCP tools（提交 42a50b7）
把 P1.3 加的 Memory CRUD API 接通到 MCP：
- `radiomind_get_memory` / `radiomind_update_memory` / `radiomind_delete_memory`
- `radiomind_list_memories`（支持 user/agent/session scope 过滤）
- `radiomind_memory_history`（审计轨迹）
- `radiomind_delete_scope`（scope 必填，无 scope 拒绝执行）

### 迁移框架（提交 42a50b7）
`storage/migrations.py`：`@register(version=N)` 装饰 + `apply_migrations()` 顺序执行。把 v2（privacy）和 v3（多用户 + memory_history）两次迁移从内联 if 分支抽出。以后加一次迁移只需写一个函数 + 升 `CURRENT_SCHEMA_VERSION`。幂等性验证通过。

## 沙箱
全程使用 `RADIOMIND_HOME=/tmp/rm-sandbox-*`，每次测完校验 `~/.radiomind/data/hdc/habits.json` 仍为空列表，真实记忆未被污染。

## 回归核查
LoCoMo-lite baseline 在 P3 改完后重跑：Recall@5 仍 0.710（34/50 perfect，13 zero），Recall@10 0.730。未出现检索回归。

## 未做（酌情留给后续）
P3 里还有若干项没在本轮做：
- Prompt 重写（EVIDENCE / FALSIFIER 结构）
- 异构模型（guardian/explorer/reducer 用不同模型）
- KG entity resolution
- async/batch API
- UX 细节（progress bar、更好的错误信息等）

这些是「让已经能跑的东西更好跑」，不是阻塞项，下轮再做。

## 本轮提交
```
26c93cd log: P1 execution
4f22bbc P2.1: LoRA data quality
1aa56f3 P2.2+P2.3: LoRA A/B eval + correct deploy
42a50b7 P3: session persistence + CRUD MCP tools + migration framework
```
