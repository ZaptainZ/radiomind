# RadioMind

**A memory module that actually learns from conversations — plug it into any AI agent.**

```python
import radiomind

mind = radiomind.connect()
mind.add([{"role": "user", "content": "I run every morning and sleep much better since"}])
mind.search("health habits")       # finds it, even weeks later
print(mind.digest())               # "User: morning runner, values sleep quality"
```

4 methods. Zero config. Your agent remembers everything and gets smarter over time.

[中文版](README_zh.md) · [Quickstart](docs/quickstart.md) · [Integration Guide](docs/integration.md) · [API Reference](docs/api-reference.md)

---

## What it does

Most AI memory systems store text and retrieve it. RadioMind goes further — it **distills conversations into habits**:

- "I like running" + "running helps me sleep" → **habit:** *"exercise improves this user's sleep quality"*
- That habit then influences future conversations **across domains** — work, health, learning, anything.

| | Typical memory (Mem0, Zep, etc.) | RadioMind |
|---|---|---|
| Store & search | ✅ | ✅ |
| Distill habits from conversations | ❌ | ✅ |
| Cross-domain insight ("health tip improves work advice") | ❌ | ✅ |
| Gets smarter without extra LLM cost | ❌ | ✅ |
| Privacy controls per topic | ❌ | ✅ |
| Knows itself (tracks its own state) | ❌ | ✅ |

## Install & use

```bash
pip install radiomind
```

```python
import radiomind

mind = radiomind.connect()

# Your agent's conversation loop:
mind.add(messages)                    # feed conversations in
results = mind.search("query")       # get relevant memories back
system_prompt = mind.digest()        # inject user context (~250 tokens)
mind.refine()                        # distill habits (automatic)
```

That's the entire API. Everything else — domain detection, privacy tagging, habit encoding, memory pruning — happens inside automatically.

**Works with any framework:**

```python
# Pass your existing LLM client — RadioMind auto-detects the type
mind = radiomind.connect(llm=openai_client)
mind = radiomind.connect(llm=anthropic_client)
mind = radiomind.connect(llm=lambda prompt, system: my_llm(prompt))

# Or just have an API key in your environment — RadioMind finds it
# OPENAI_API_KEY, ANTHROPIC_API_KEY, DASHSCOPE_API_KEY, DEEPSEEK_API_KEY...
# Supports 11 providers. No config file needed.
```

## Plug into your stack

| Method | One-line setup | Best for |
|--------|---------------|----------|
| **Python** | `radiomind.connect()` | Any Python agent |
| **MCP** | `claude mcp add radiomind -- radiomind mcp-server` | Claude Desktop, Cursor, VS Code |
| **REST** | `radiomind serve --port 8730` | Any language, remote |
| **CLI** | `radiomind search "query"` | Scripts, cron, hooks |

9 MCP tools, 6 REST endpoints, 20+ CLI commands. See [Integration Guide](docs/integration.md).

### Inside AI assistants (Claude Code, Codex, Hermes)

When running inside an AI assistant, RadioMind lets **the assistant itself do the thinking** — no extra LLM calls, no extra cost:

```
Your AI assistant calls: radiomind_refine_step("prepare", domain="health")
RadioMind returns:       "Here are 10 health memories. As the Guardian, evaluate..."
Your assistant reasons:  "These memories consistently show exercise improving sleep..."
RadioMind records the insight and moves to the next step.
```

The assistant plays three debate roles (Guardian, Explorer, Reducer), then RadioMind distills the result into a lasting habit. Zero extra API calls.

---

## How it works (for the curious)

<details>
<summary><b>Architecture — inspired by how the brain actually remembers</b></summary>

RadioMind models the brain's complementary learning systems:

```
Meta ─── User profile + system self-awareness
L4 ───── External knowledge ("memory reads books")
L3 ───── Habit memory: HDC vectors + LoRA adapters (neocortex)
           ├─ "Chat" refinement: three-body debate
           └─ "Dream" refinement: pruning + free association
L2 ───── Memory notes: 3D pyramid — domain × time × abstraction (hippocampus)
L1 ───── Attention gate: extract facts from conversations (working memory)
L0 ───── Base model weights (swappable, never hardcoded)
```

| Brain | Function | RadioMind |
|-------|----------|-----------|
| Prefrontal cortex | Working memory | L1 attention gate |
| Hippocampus | Fast episodic encoding | L2 3D pyramid (SQLite FTS5) |
| Neocortex | Slow consolidation | L3 HDC + LoRA |
| Sleep (SHY) | Synaptic pruning | "Dream" refinement |
| Social learning | Discussion + recall | "Chat" three-body debate |
| Cultural memory | Books, education | L4 Shortwave library |

</details>

<details>
<summary><b>Three-body debate — why three roles, not two</b></summary>

Two debaters tend to merge or one dominates. Three debaters with competing interests produce more robust conclusions (ICLR 2025 DMAD: 91% vs 82% accuracy).

```
Guardian (魏) — "Does this fit what we already know?"
Explorer (吴) — "Is there something new here?"
Reducer  (蜀) — "Can we simplify?"

Vote: 2 out of 3 must agree → candidate insight → verified in future conversations
```

Inspired by Three Kingdoms strategy and three-body problem dynamics.

</details>

<details>
<summary><b>LoRA training — memories that don't need retrieval</b></summary>

Periodically, RadioMind fine-tunes a small local model (0.5–3B) on your habits:

```bash
radiomind train --iters 100    # ~5 min on MacBook, uses Apple MLX
```

After training, the model "just knows" your preferences — like how you know fire is hot without looking it up. The adapter is a few MB and loads in under a second.

</details>

<details>
<summary><b>Rust daemon — for 100K+ memories and 24/7 uptime</b></summary>

Storage hot paths run in a Rust daemon:

```
Python logic layer (LLM calls, prompts, training)
         ↕ Unix socket JSON Lines
Rust daemon (SQLite, FTS5, HDC, knowledge graph, 16 IPC methods)
```

```bash
cd rust-core && cargo build --release
./target/release/radiomind-daemon
```

Python auto-detects the daemon and routes operations through IPC.

</details>

<details>
<summary><b>Privacy — some topics stay private</b></summary>

Each domain gets a privacy level:

- **open** — flows freely across domains (default)
- **guarded** — only patterns/principles cross domain boundaries, not raw facts (auto-applied to health, finance)
- **sealed** — never leaves its domain

</details>

---

## Part of the Radio ecosystem

| Project | What it does |
|---------|-------------|
| **[RadioHeader](https://github.com/ZaptainZ/radioheader)** | Cross-project experience framework for coding agents |
| **RadioMind** | Bionic memory module (this repo) |
| **RadioHand** | Personal agent framework (planned) |

RadioMind is the default memory backend for RadioHeader and RadioHand, but works standalone with any agent.

## Research

Built on: Complementary Learning Systems (McClelland 1995), Synaptic Homeostasis Hypothesis (Tononi & Cirelli 2006), Hyperdimensional Computing (Kanerva 2009), Multi-Agent Debate (ICLR 2025 DMAD), LoRA (Hu 2021), NeuroDream (2026), Stigmergy (Grassé 1959).

## License

MIT
