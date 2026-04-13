# RadioMind

**Bionic memory core for AI agents — the brain that grows with you.**

> *Not another vector database. RadioMind distills scattered conversations into deep habits through biologically-inspired "chatting" and "dreaming", then enforces their use.*

[中文版](#中文) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Integration](#integration)

---

## Why RadioMind?

Every AI memory system today stores and retrieves. None of them **think about what they've stored**.

RadioMind is different. Inspired by neuroscience — hippocampal encoding, neocortical consolidation, synaptic homeostasis during sleep — it doesn't just remember. It **refines memories into habits**, discovers hidden cross-domain patterns, and makes sure the agent actually uses what it has learned.

| Capability | Mem0 / Zep / mempalace | **RadioMind** |
|-----------|----------------------|---------------|
| Store & retrieve | ✅ | ✅ |
| Cross-domain experience flow | ❌ | ✅ Shortwave distillation |
| Active refinement | ❌ | ✅ Three-body debate + dream pruning |
| Enforce memory usage | ❌ | ✅ Search→Apply→Trace contract |
| LoRA internalization | ❌ (Hermes exports data, no loop) | ✅ Full loop: habits → JSONL → MLX → adapter |
| Privacy-aware cross-domain | ❌ | ✅ open / guarded / sealed per domain |
| Self-awareness | ❌ | ✅ Dual profiling (user + system) |

## Architecture

RadioMind mirrors the human brain's complementary learning systems:

```
┌─────────────────────────────────────────────────────────────┐
│  Meta: Dual Profiling (user + self)                         │
│  "Know thyself, know thy user"                              │
├─────────────────────────────────────────────────────────────┤
│  L4  External Knowledge ── "Memory reads books"             │
│      Shortwave library + Learn + Community (Stigmergy)      │
├─────────────────────────────────────────────────────────────┤
│  L3  Habit Memory ── Neocortex                              │
│      HDC hypervectors (10,000-bit) + LoRA adapters          │
│      ┌─ "Chat": Three-body debate (Guardian/Explorer/       │
│      │          Reducer) — creates new insights             │
│      └─ "Dream": SHY pruning + DMN wandering —             │
│                  prunes redundancy, discovers meta-patterns │
├─────────────────────────────────────────────────────────────┤
│  L2  Memory Notes ── Hippocampus (3D Pyramid)               │
│      SQLite FTS5, indexed by domain × time × abstraction    │
│      Attention-style retrieval: principles → patterns → facts│
├─────────────────────────────────────────────────────────────┤
│  L1  Memory Drafts ── Working Memory                        │
│      Attention gate: 15+ extraction patterns                │
│      Domain auto-detection, privacy auto-tagging            │
├─────────────────────────────────────────────────────────────┤
│  L0  Base Model ── Instinct (swappable, never hardcoded)    │
└─────────────────────────────────────────────────────────────┘
```

**Neuroscience mapping:**

| Brain Structure | Function | RadioMind |
|----------------|----------|-----------|
| Prefrontal cortex | Working memory | L1 attention gate |
| Hippocampus | Fast episodic encoding | L2 3D pyramid |
| Neocortex | Slow semantic consolidation | L3 HDC + LoRA |
| Sleep (SHY) | Synaptic pruning | "Dream" refinement |
| Social learning | Retrieval practice + discussion | "Chat" refinement |
| Cultural memory | Books, education | L4 Shortwave |
| Metacognition | Self-awareness | Dual profiling |

### Three-Body Debate ("Chat" Refinement)

Inspired by Three Kingdoms: two agents compromise or merge, three agents check and balance each other. ICLR 2025 DMAD confirms heterogeneous 3-agent teams achieve 91% vs 82% for 2-agent.

```
Guardian (魏) ─── consistency ───┐
Explorer (吴) ─── novelty ──────┤── vote (2:1 passes) ── candidate insight
Reducer  (蜀) ─── parsimony ────┘
```

### Dream Refinement

Like sleep consolidation (Tononi & Cirelli's Synaptic Homeostasis Hypothesis):

1. **Pruning (SHY):** decay unused memories, merge redundancies, resolve contradictions
2. **Wandering (DMN):** random association across domains → discover meta-patterns
3. **Journal:** record what was pruned and what was discovered

### Rust Daemon

Hot paths run in a Rust daemon (`radiomind-daemon`) for 10M+ memory scale and 7×24 uptime:

```
Python logic layer (LLM calls, prompts, training)
         ↕ Unix socket JSON Lines
Rust daemon (SQLite, FTS5, HDC, knowledge graph, 16 IPC methods)
```

## Quick Start

### Install

```bash
pip install radiomind

# Optional: LoRA training on Apple Silicon
pip install 'radiomind[train]'

# Optional: embedding (ONNX MiniLM)
pip install 'radiomind[embedding]'
```

### Python API

```python
from radiomind import RadioMind
from radiomind.core.types import Message

mind = RadioMind()
mind.initialize()

# Ingest conversations
mind.ingest([
    Message(role="user", content="我叫小明"),
    Message(role="user", content="我喜欢每天早上跑步"),
    Message(role="user", content="我讨厌加班"),
])

# Search (pyramid: principles → patterns → facts)
results = mind.search("运动")

# Query L3 habits (HDC)
habits = mind.query_habits("health")

# Trigger refinement
mind.trigger_chat(domain="health")   # three-body debate
mind.trigger_dream()                  # pruning + wandering

# Context digest (for system prompt injection, ~250 tokens)
digest = mind.get_context_digest()

# User profile (learned from conversations)
profile = mind.get_user_profile()

# LoRA training (MLX on Apple Silicon)
mind.train(iters=100)

mind.shutdown()
```

### CLI

```bash
radiomind init                          # initialize data directory
radiomind ingest conversation.jsonl     # ingest conversation history
radiomind search "跑步"                 # pyramid search
radiomind chat --domain health          # three-body debate
radiomind dream                         # pruning + wandering
radiomind train --iters 100             # LoRA fine-tuning
radiomind status                        # memory statistics
radiomind learn "运动改善心血管健康"      # add external knowledge

# Community
radiomind community sync                # sync from community pool
radiomind community contribute          # share insights (PII-filtered)
radiomind community vote entry-id +1    # vote on entries

# RadioHeader bridge
radiomind migrate-radioheader           # import RadioHeader data
radiomind rh-search "白屏"              # RadioHeader-compatible search
radiomind rh-consolidate                # run consolidation

# MCP Server (for Claude Desktop, Cursor, VS Code)
radiomind mcp-server
```

### MCP Server

```bash
# Add to Claude Desktop
claude mcp add radiomind -- radiomind mcp-server
```

8 tools available: `radiomind_search`, `radiomind_ingest`, `radiomind_learn`, `radiomind_habits`, `radiomind_digest`, `radiomind_status`, `radiomind_chat`, `radiomind_dream`.

### Hermes Agent Integration

RadioMind works as a Hermes Memory Provider:

```bash
# In Hermes config
hermes config set memory.provider radiomind
```

Features: `system_prompt_block`, `prefetch`, `sync_turn` (non-blocking), `on_session_end` (auto-dream), `on_memory_write`.

### Rust Daemon (Optional, for scale)

```bash
cd rust-core && cargo build --release
./target/release/radiomind-daemon       # listens on ~/.radiomind/radiomind.sock
```

The Python layer auto-detects the daemon and routes storage operations through IPC.

## Configuration

All configuration lives in `~/.radiomind/config.toml`. **Nothing is hardcoded** — LLM, models, backends, cost tiers are all configurable.

```toml
[llm]
default_backend = "openai"   # or "ollama"

[llm.openai]
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key = "your-key"
model = "qwen-plus"

[llm.models]
economy = "qwen-turbo"       # for daily refinement ($0)
standard = "qwen-plus"       # for better quality
deep = "qwen-max"            # for deep thinking

[refinement]
cost_mode = "economy"        # economy | standard | deep

[hdc]
dim = 10000                  # hypervector dimension
```

## Radio Family

RadioMind is part of the Radio ecosystem:

| Project | Role | Status |
|---------|------|--------|
| **[RadioHeader](https://github.com/ZaptainZ/radioheader)** | Rules & cross-project experience | Released |
| **RadioMind** | Bionic memory core | This repo |
| **RadioHand** | Personal agent framework | Planned |

```
RadioHeader (头/rules) → RadioMind (脑/memory) → RadioHand (手/execution)
```

## Research Foundations

- **Complementary Learning Systems** (McClelland et al., 1995) — hippocampus + neocortex
- **Synaptic Homeostasis Hypothesis** (Tononi & Cirelli, 2006) — sleep prunes weak synapses
- **Hyperdimensional Computing** (Kanerva, 2009) — 10,000-dim vectors for brain-like memory
- **NeuroDream** (2026) — 38% less forgetting, 17.6% better zero-shot transfer
- **DMAD / Multi-Agent Debate** (ICLR 2025) — heterogeneous 3-agent teams outperform 2-agent
- **LoRA** (Hu et al., 2021) — low-rank adaptation for parametric memory
- **Stigmergy** (Grassé, 1959) — ant-trail pheromone decay for community knowledge scoring

## License

MIT

---

<a name="中文"></a>

# RadioMind — 仿生记忆核心

**为 AI Agent 提供"越用越懂你"的深层记忆能力。**

> *不是又一个向量数据库。RadioMind 通过仿生的"聊天"和"做梦"机制，将零散对话炼化为深层习惯记忆，并确保 Agent 真正使用它们。*

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
| 隐私分级 | ❌ | ✅ 开放/半开/封闭，按领域配置 |
| 自我意识 | ❌ | ✅ 双侧写（用户+系统自画像） |

## 架构：四层仿生记忆

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

### 三体辩论（"聊天"炼化）

灵感来自三国演义的三方制衡 + 三体问题的复杂涌现。两方容易吞并或妥协，三方互相牵制产生更稳健的结论：

- **守护者 (魏)**: 新记忆和已有习惯一致吗？
- **探索者 (吴)**: 这是不是新模式？值得记录！
- **精简者 (蜀)**: 真的需要吗？能和已有的合并吗？

三方各出论点 → 投票（2:1 通过）→ 候选洞察 → 后续验证确认。

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
from radiomind import RadioMind
from radiomind.core.types import Message

mind = RadioMind()
mind.initialize()

# 导入对话
mind.ingest([
    Message(role="user", content="我叫小明"),
    Message(role="user", content="我喜欢跑步"),
])

# 搜索（金字塔：原则→模式→事实）
results = mind.search("运动")

# 三体辩论
mind.trigger_chat()

# 做梦
mind.trigger_dream()

# 上下文摘要（注入 system prompt）
digest = mind.get_context_digest()

mind.shutdown()
```

### CLI 命令

```bash
radiomind init                     # 初始化
radiomind ingest chat.jsonl        # 导入对话
radiomind search "跑步"            # 金字塔搜索
radiomind chat                     # 三体辩论
radiomind dream                    # 做梦炼化
radiomind train --iters 100        # LoRA 微调
radiomind status                   # 统计
radiomind community sync           # 同步社区知识
radiomind mcp-server               # 启动 MCP 服务
```

### 接入方式

| 方式 | 命令 |
|------|------|
| Python API | `from radiomind import RadioMind` |
| CLI | `radiomind search "query"` |
| MCP Server | `claude mcp add radiomind -- radiomind mcp-server` |
| Hermes Agent | `hermes config set memory.provider radiomind` |
| RadioHeader | `radiomind migrate-radioheader` |

## 配置

`~/.radiomind/config.toml` — 一切不写死：

```toml
[llm]
default_backend = "openai"

[llm.openai]
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-plus"

[llm.models]
economy = "qwen-turbo"      # 日常炼化
standard = "qwen-plus"      # 更好质量
deep = "qwen-max"           # 深度思考

[refinement]
cost_mode = "economy"
```

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
