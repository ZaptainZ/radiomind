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

```bash
pip install radiomind
```

```python
import radiomind

mind = radiomind.connect()

# 1. Add conversations → auto-extracts facts, detects domains, builds profile
mind.add([
    {"role": "user", "content": "My name is Alice"},
    {"role": "user", "content": "I run every morning"},
    {"role": "user", "content": "I hate overtime work"},
])

# 2. Search → pyramid retrieval (principles → patterns → facts) + HDC habits
results = mind.search("exercise")

# 3. Digest → compressed user context for system prompt injection (~250 tokens)
print(mind.digest())
# User: name: Alice
# Style: morning runner, dislikes overtime
# Memory: 3 entries across health, work

# 4. Refine → three-body debate + dream pruning (needs LLM configured)
mind.refine()

mind.close()
```

That's the entire API. 4 methods. Everything else happens automatically inside.

Need more control? Access the [advanced API](docs/api-reference.md) via `mind.advanced`.

## Integration

6 ways to connect RadioMind to your stack:

| Method | Setup | Best for |
|--------|-------|----------|
| **Python API** | `radiomind.connect()` | Python agents, LangChain |
| **REST API** | `radiomind serve` | Any language, remote access |
| **MCP Server** | `claude mcp add radiomind -- radiomind mcp-server` | Claude Desktop, Cursor |
| **Hermes** | `hermes config set memory.provider radiomind` | Hermes Agent |
| **RadioHeader** | `radiomind migrate-radioheader` | Existing RadioHeader users |
| **CLI** | `radiomind search "query"` | Shell scripts, cron |

### REST API (cross-language)

```bash
pip install 'radiomind[server]'
radiomind serve --port 8730          # OpenAPI docs at /docs
```

```bash
curl -X POST localhost:8730/v1/add -d '{"messages":[{"role":"user","content":"I like running"}]}'
curl -X POST localhost:8730/v1/search -d '{"query":"exercise"}'
curl localhost:8730/v1/digest
```

See the full [Integration Guide](docs/integration.md) for code examples in Python, JavaScript, Go, and more.

## LLM — Zero Config

RadioMind **auto-detects** your LLM. No configuration needed for most users.

| Priority | Source | You do... |
|----------|--------|-----------|
| 1 | Host framework | `radiomind.connect(llm=your_client)` — auto-wraps OpenAI, Anthropic, any callable |
| 2 | Environment variable | Just have `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` etc. in your env |
| 3 | Local Ollama | Just have Ollama running on localhost |
| 4 | `config.toml` | Only for advanced model routing — most users never need this |
| 5 | No LLM | `add`/`search`/`digest` still work. `refine` is a no-op |

Supported env vars: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `TOGETHER_API_KEY`, `MOONSHOT_API_KEY`, `ZHIPUAI_API_KEY`, `SILICONFLOW_API_KEY`, `MISTRAL_API_KEY`, `FIREWORKS_API_KEY`.

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
