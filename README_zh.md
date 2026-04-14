# RadioMind — 仿生记忆核心

**为 AI Agent 提供"越用越懂你"的深层记忆能力。**

> *不是又一个向量数据库。RadioMind 通过仿生的"聊天"和"做梦"机制，将零散对话炼化为深层习惯记忆，并确保 Agent 真正使用它们。*

[English](README.md) · [架构](#架构) · [快速开始](#快速开始) · [接入方式](#接入方式) · [文档](docs/)

**文档：** [Quickstart](docs/quickstart.md) · [集成指南](docs/integration.md) · [API 参考](docs/api-reference.md)

---

## 为什么选 RadioMind？

2026 年的 AI 记忆框架（Mem0、Zep、mempalace……）全部聚焦在"存"和"检索"上。**没有一个在"思考"自己存了什么。**

RadioMind 受神经科学启发——海马体快速编码、新皮层慢速巩固、睡眠中的突触修剪——它不只是记忆，而是将记忆**炼化为习惯**：

| 能力 | 现有框架 | **RadioMind** |
|------|---------|---------------|
| 存储检索 | ✅ | ✅ |
| 跨领域经验流动 | ❌ | ✅ Shortwave 提纯 |
| 主动炼化 | ❌ | ✅ 三体辩论 + 做梦修剪 |
| 强制记忆使用 | ❌ | ✅ 搜→用→追 行为契约 |
| LoRA 内化 | ❌ | ✅ 习惯→训练数据→MLX→adapter |
| 宿主 AI 驱动炼化 | ❌ | ✅ 分步式炼化 — 零额外 LLM 费用 |
| 隐私分级 | ❌ | ✅ 开放/半开/封闭，按领域配置 |
| 自我意识 | ❌ | ✅ 双侧写（用户+系统自画像） |

## 架构

```
Meta 元认知 ─── 用户侧写 + 系统自画像（运行时自省，不写死）
L4 外挂知识 ─── Shortwave 库："让记忆去读书"
L3 习惯记忆 ─── HDC 超维向量 + LoRA adapter（新皮层）
     ├─ "聊天"炼化: 三体博弈（守护者/探索者/精简者）
     └─ "做梦"炼化: SHY 修剪 + DMN 神游
L2 记忆笔记 ─── 3D 金字塔 (domain × time × level)（海马体）
L1 记忆草稿 ─── 注意力门控（工作记忆）
L0 本能 ─────── 基模权重（可更换，不绑定）
```

### 两种炼化模式

| | 宿主驱动（推荐） | 自驱动 |
|---|---|---|
| **谁在思考** | 宿主 AI（Claude、GPT 等） | RadioMind 自己的 LLM |
| **额外费用** | 零 — 用宿主已有的额度 | API 调用费 或 本地 Ollama |
| **推理质量** | 宿主级别（Claude/GPT） | 经济模型级别 |
| **适用场景** | Claude Code、Codex、Hermes、MCP | CLI 定时任务、独立部署 |
| **调用方式** | `radiomind_refine_step`（MCP/CLI） | `mind.refine()` / `radiomind chat` |

**宿主驱动模式**将炼化拆为步骤。RadioMind 出题，宿主 AI 思考：

```
prepare → RadioMind 返回守护者 prompt → 宿主 AI 推理回答
guardian → RadioMind 返回探索者 prompt → 宿主 AI 推理回答
explorer → RadioMind 返回精简者 prompt → 宿主 AI 推理回答
reducer → RadioMind 返回综合 prompt → 宿主 AI 综合
synthesize → RadioMind 记录洞察到 L3

RadioMind = 组织者 | 宿主 AI = 思考者
```

这与 RadioHeader 在 Claude Code 中的工作方式完全一致——Echo、Shortwave 提纯都是由 CC 的 Claude 在对话中完成的。

### 三体辩论

灵感来自三国演义的三方制衡 + 三体问题的复杂涌现（ICLR 2025 DMAD: 91% vs 82%）：

```
守护者 (魏) ─── 一致性 ───┐
探索者 (吴) ─── 新颖性 ──┤── 投票 (2:1 通过) ── 候选洞察
精简者 (蜀) ─── 简洁性 ──┘
```

### 做梦炼化

对标突触稳态假说 (SHY, Tononi & Cirelli)：

1. **修剪**: 矛盾消解 / 冗余合并 / 未使用记忆衰减归档
2. **神游**: 随机挑选不相关的记忆，寻找隐藏的跨域关联
3. **梦境记录**: 修剪直接执行，神游发现标记候选+置信度

### Rust 守护进程

热路径运行在 Rust 守护进程中，支持 10 万+ 条记忆和 7×24 常驻：

```
Python 逻辑层（LLM 调用、prompt、训练）
       ↕ Unix socket JSON Lines
Rust 守护进程（SQLite、FTS5、HDC、知识图谱，16 个 IPC 方法）
```

## 快速开始

```bash
pip install radiomind
```

```python
import radiomind

# 直接连接 — LLM 从环境变量、Ollama 或宿主框架自动检测
mind = radiomind.connect()

# 或直接传入你框架的 LLM（自动识别 OpenAI、Anthropic、任何 callable）
# mind = radiomind.connect(llm=openai_client)

# 1. 添加 — 自动提取事实、检测领域、构建用户画像
mind.add([
    {"role": "user", "content": "我叫小明"},
    {"role": "user", "content": "我每天早上跑步"},
    {"role": "user", "content": "我讨厌加班"},
])

# 2. 搜索 — 金字塔检索（原则→模式→事实）+ HDC 习惯匹配
results = mind.search("运动")

# 3. 摘要 — 压缩的用户上下文，注入 system prompt（~250 tokens）
print(mind.digest())

# 4. 炼化 — 三体辩论 + 做梦修剪（LLM 自动检测）
mind.refine()

mind.close()
```

**4 个方法，零 LLM 配置。** 内部全自动完成。

需要更多控制？通过 `mind.advanced` 访问[高级 API](docs/api-reference.md)。

## 接入方式

7 种方式接入你的技术栈：

| 方式 | 设置 | 适用场景 |
|------|------|---------|
| **Python API** | `radiomind.connect()` 或 `connect(llm=client)` | Python Agent、任何框架 |
| **分步炼化** | `mind.refine_step("prepare", domain="health")` | CC、Codex、Hermes — 宿主 AI 思考 |
| **REST API** | `radiomind serve` | 跨语言、远程调用 |
| **MCP Server** | `claude mcp add radiomind -- radiomind mcp-server` | Claude Desktop、Cursor、VS Code |
| **Hermes** | `hermes config set memory.provider radiomind` | Hermes Agent |
| **RadioHeader** | `radiomind migrate-radioheader` | 已有 RadioHeader 用户 |
| **CLI** | `radiomind search "query"` | Shell 脚本、Cron |

### 分步炼化（宿主 AI 模式）

在 AI 框架内运行时，宿主 AI 负责思考：

```bash
# MCP 工具 — Claude Desktop/Cursor 自动调用
radiomind_refine_step(step="prepare", domain="health")
# → 返回守护者 prompt，宿主 AI 推理回答

# CLI — 用于 RadioHeader hooks
radiomind refine-step prepare --domain health
radiomind refine-step guardian --response "这些记忆是一致的..."
radiomind refine-step explorer --response "我发现了新模式..."
radiomind refine-step reducer --response "可以合并为一条..."
radiomind refine-step synthesize --response "INSIGHT: ..."
```

### REST API（跨语言）

```bash
pip install 'radiomind[server]'
radiomind serve --port 8730          # OpenAPI 文档在 /docs
```

```bash
curl -X POST localhost:8730/v1/add -d '{"messages":[{"role":"user","content":"我喜欢跑步"}]}'
curl -X POST localhost:8730/v1/search -d '{"query":"运动"}'
curl localhost:8730/v1/digest
```

完整接入指南见 [Integration Guide](docs/integration.md)。

## LLM — 零配置

RadioMind **自动检测**环境中的 LLM，大多数用户无需任何配置。

| 优先级 | 来源 | 你需要做的 |
|--------|------|-----------|
| 1 | 宿主 AI（分步模式） | 什么都不用做 — 宿主 AI 就是 LLM，零额外费用 |
| 2 | 框架 LLM 传入 | `radiomind.connect(llm=client)` — 自动识别 OpenAI/Anthropic/callable |
| 3 | 环境变量 | 已有 `OPENAI_API_KEY` 等 → 自动使用 |
| 4 | 本地 Ollama | 装了 Ollama 就能用 |
| 5 | `config.toml` | 高级模型路由 — 大多数用户不需要 |
| 6 | 无 LLM | `add`/`search`/`digest` 正常工作，`refine` 静默跳过 |

支持 11 个 API provider 的环境变量自动检测：OpenAI、Anthropic、DashScope(Qwen)、DeepSeek、Groq、Together、Moonshot、智谱、硅基流动、Mistral、Fireworks。

## Radio 家族

| 项目 | 角色 | 隐喻 |
|------|------|------|
| [RadioHeader](https://github.com/ZaptainZ/radioheader) | 规则与跨项目经验 | 头 |
| **RadioMind** | 仿生记忆核心 | 脑 |
| RadioHand | 个人 Agent 框架 | 手 |

```
头定规则 → 脑存记忆 → 手去执行
```

## 许可

MIT
