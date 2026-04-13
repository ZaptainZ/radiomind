# RadioMind

**Bionic memory core for AI agents — the brain that grows with you.**

> *Not another vector database. RadioMind distills scattered conversations into deep habits through biologically-inspired "chatting" and "dreaming", then enforces their use.*

[中文版](README_zh.md) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Integration](#integration) · [Docs](docs/)

**Documentation:** [Quickstart](docs/quickstart.md) · [Integration Guide](docs/integration.md) · [API Reference](docs/api-reference.md)

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
