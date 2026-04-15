# 真实审计轮（用真数据跑，有对比有数字）

日期：2026-04-15
执行：Claude Code
上游：`2026-04-15-p3-polish-cc.md`

## 背景

用户问："所有的更新，是否有审计，审计的确定性能保证吗？" 我坦白承认之前的审计只是静态代码审 + sandbox 单测，关键环节（LoRA 训练闭环、真实 LLM 三体输出、真实数据迁移）没跑过。用户授权："配 CI；用我真实数据跑 LoRA 和 LLM；有备份就放心改；可以的话跑一个有影响力的 benchmark。"

## 做了什么

### 0. 备份
`~/radiomind-backup-20260415-181603/`（94MB）：
- `dotradiomind/`（完整 ~/.radiomind，含 897KB DB + 28KB KG）
- `radioheader/`（~/.claude/radioheader 全量）
- `claude-settings.json`, `dotcodex/`
真实 home 全程 mtime 最后时刻对比：114035 bytes 内容完全一致，745/1 active/archived 不变。

### 1. GitHub Actions CI（提交 `c849df3`）
`.github/workflows/ci.yml` — 每次 push + PR 跑四条：
- **test**：pytest 在 Python 3.11/3.12/3.13 matrix 上跑（230 必须全过）
- **bench-locomo**：`python bench/locomo_lite/run.py`，R@5 < 0.3 就退出码 1
- **lint**：遍历导入所有 `radiomind.*` 模块，捕循环/语法错误
- **sandbox-guard**：新 HOME + RADIOMIND_HOME 跑 pytest，跑完检查 `$HOME/.radiomind` 是否被创建——这正是抓住下面 #3 bug 的门禁机制

`.github/workflows/lora-smoke.yml` — 手动触发，在 macos-latest 跑 `mlx_lm.fuse` 冒烟。

### 2. 真实审计发现三条 bug（提交 `a2840d9`）

**真跑才能暴露**的问题，单测没抓到：

#### bug1（严重）：RADIOMIND_HOME 被 config.toml 静默覆盖
`Config.load()` 的顺序：
```python
cfg.data["general"]["home"] = str(home)  # 从 env 设
_deep_merge(cfg.data, user)              # config.toml 覆盖回去！
```
实际后果：把 `/tmp/rm-real-test` 当沙箱跑，但真实 `~/.radiomind` 被迁移。数据没丢（114035 字节一致），但 schema v2 → v3 在真实 home 上发生了。单测没抓是因为测试沙箱里没有 config.toml 覆盖 [general] home 的情况。

**修**：env 应用移到 file merge **之后**，env 永远胜。加了 `test_env_home_beats_config_toml` 回归。

#### bug2：老 DB 启动崩溃
`SCHEMA_SQL` 里 `CREATE INDEX ... user_id` 在 schema v1/v2 DB 上跑会炸（列还没加）。**修**：所有 v2+ 索引移进 migrations.py 的对应 migration。

#### bug3：`model_used` 报错
`RefinementResult.model_used = config.get("llm.ollama.model")` 硬编码到 Ollama path。实际用 Dashscope/Qwen 的用户看到假 "qwen3:0.6b"。**修**：读 `llm.{default_backend}.model`，fallback ollama。

### 3. 真实 LLM 三体辩论
配 Qwen API（用户 config.toml 里的 `qwen-turbo` via Dashscope）。对真实 DB 的 `rust` domain（108 条）跑 `trigger_chat`：
- 6.7s 完成，859 tokens（¥≈0.01）
- 2 条 insight，都带 EVIDENCE + FALSIFIER
- 内容真的贴用户记忆（引用 `serde rename`、轻量物理引擎替换 rapier3d 等）
- **验证 prompts 对真实 LLM 有效**

副作用：两条 insight 的 falsifier 被模型复制了同一句——LLM 输出质量问题，不是 parser 问题。

### 4. Embedding 装上跑真实 R@5（提交 `a2840d9`）
`pip install onnxruntime tokenizers`，下载 ~400MB 嵌入模型。LoCoMo-lite 真实对比：

| 配置 | R@5 | R@10 | 延迟 | Perfect | Zero |
|------|-----|------|------|---------|------|
| 无 embedder | 0.710 | 0.730 | 0.3ms | 34/50 | 13/50 |
| + embedder | **0.750** | **0.807** | 28.9ms | 36/50 | 11/50 |

Embedder 净提升 **R@5 +4%, R@10 +7.7%**，代价 28.9ms/query。

### 5. LoRA 真训真评（提交 `cbe753a`）
对真实 10 habits + 43 domains 跑整套 P2 流水线：

**数据生成**（refused gate 通过）：
- 82 train + 20 valid（不重叠），36 dupes 剔除，1 过短剔除

**训练** MLX Qwen2.5-0.5B-Instruct-4bit, rank=8, 150 iters, 107s：

| Iter | Val loss | Train loss |
|------|----------|-----------|
| 1    | 4.304    | - |
| 25   | 0.913    | - |
| 50   | 0.553    | 0.657 |
| 75   | 0.510    | - |
| **100** | **0.492** | 0.367 |
| **125** | **0.486 (min)** | - |
| 150  | 0.492 (↑) | 0.202 |

**明显的过拟合信号**：val 在 125 触底 0.486，iter 150 train 降到 0.202 但 val 回升到 0.492。`early_stop_patience=3` 声明了但没接到 mlx_lm 训练循环——**第 4 个 bug 被暴露了**。先记录，后修。

**A/B 评估** 用 mlx_lm 直接加载 base vs base+adapter，对 8 个记忆问题打分：

| | base | LoRA | delta |
|-|------|------|-------|
| mean overlap | 0.345 | **0.424** | **+0.079 (+23% rel)** |
| wins/losses/ties | | **5 / 2 / 1** | |

**定性观察**（节选）：
- Q: "告诉我一件关于我的事"
  - Base: "作为 AI，我无法回答关于自己的问题..."
  - **LoRA: "动态阻尼机制在处理离群参数时比硬编码上限更受用户欢迎"** ← 用户真实 habit 复述
- Q: "Rust 典型模式"
  - Base: 通用 Rust 所有权教程
  - **LoRA: "使用 `#[serde(rename = "X")]`..."** ← 用户记忆里真实存在

LoRA 能实打实召回用户模式。

### 6. 影响力 benchmark — LoCoMo10 真实（提交 `cbe753a`）
下载 Snap Research / ACL 2024 的 `locomo10.json`（2.8MB，10 对话×1986 QA）。对 conversation 0 跑 retrieval-only eval（不用 LLM 做答案抽取）：

| Category | n | R@5 |
|----------|---|-----|
| 1 单跳检索 | 32 | 0.062 |
| 2 多跳推理 | 37 | 0.189 |
| 3 时序推理 | 11 | **0.000** |
| 4 开域知识 | 70 | 0.214 |
| 5 对抗性 | 47 | 0.298 |
| **overall** | **197** | **0.193** |

和公开纯检索 baseline（10-25%）在同一档。cat3 = 0 暴露了 **gap**：KG 里有 `query_entity(as_of=...)` 但 pyramid search 没接到它——时序查询只是普通字符串匹配。

### 7. MCP + RadioHeader 集成
对真实数据拷贝跑 MCP server：
- 16 tools 全部注册
- `radiomind_search "Rust serde"` 返回用户真实 pattern（`#[serde(rename="oauth")]`、2m37s 编译时间等）
- Status 正确报告 745/43 domains, embedding=True

确认 RadioHeader + CC settings + RadioMind MCP 三方集成可用。

## 最终诚实账本

**跑过真数据、有 before/after 数字可证：**
- ✓ Schema v2→v3 迁移（真实 745 条 DB，字节级完好）
- ✓ 真 Qwen LLM 的 EVIDENCE/FALSIFIER 三体输出（6.7s, 859 tokens）
- ✓ Embedder 对 R@5 的提升（+4.0%, +7.7%）
- ✓ LoRA train loss + val loss 曲线（150 iters 完整记录）
- ✓ LoRA vs base 数字 A/B（+23% overlap）
- ✓ 真实 LoCoMo10 R@5 = 0.193（conv[0]）
- ✓ MCP + RadioHeader 集成（真实 DB）

**本轮发现+修的 bug：**
- bug1 env 被 config.toml 覆盖 → 修
- bug2 老 DB 启动崩 → 修
- bug3 `model_used` 硬编码 → 修
- bug4 `early_stop_patience` 声明未接 → 记录，未修

**CI 保护：**
- 4 job（test / bench / lint / sandbox-guard）推送即跑
- `sandbox-guard` 这条正是抓 bug1 类问题的门禁——以后有人再写出"测试能过但真实环境出事"的代码就会撞在 CI 上

**留给下轮的非阻塞项：**
- 接 `early_stop_patience` 到 mlx_lm callback（P2 未完成）
- 把 KG `as_of` 引入 pyramid search（解决 cat3 0 分）
- LoRA 部署（fuse → GGUF）真跑一次（需装 llama.cpp）
- 跑 LoCoMo10 剩余 9 条对话 + 跑 LongMemEval（资源允许时）

## 本轮提交
```
c849df3 ci: GitHub Actions for pytest / benchmark / imports / sandbox guard
a2840d9 audit P1: fix silent sandbox breach + v1→v3 migration + model reporting
cbe753a audit: real-data benchmarks — LoRA A/B + LoCoMo10 real
```

## 备份
`/Users/zaptain/radiomind-backup-20260415-181603/` — 94MB，保留 14 天后可以删。如需回滚：
```bash
rm -rf ~/.radiomind && cp -R /Users/zaptain/radiomind-backup-20260415-181603/dotradiomind ~/.radiomind
```
