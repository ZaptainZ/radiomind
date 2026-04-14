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

## What RadioMind adds to AI assistants

When plugged into Claude Code, Codex, Hermes, or any MCP-compatible tool, RadioMind gives the assistant abilities it doesn't have natively:

| Capability | Without RadioMind | With RadioMind |
|-----------|-------------------|----------------|
| **Remember across sessions** | Forgets after each conversation | Remembers everything, forever |
| **Know the user** | Starts fresh every time | Knows name, preferences, habits, goals |
| **Learn from mistakes** | Repeats the same errors | "Last time this approach failed because..." |
| **Connect the dots** | Each topic is isolated | "Your sleep issue might relate to the overtime you mentioned last week" |
| **Get smarter over time** | Same capability, always | Accumulates habits, refines understanding |
| **Respect privacy** | No concept of sensitivity | Health data stays guarded, sealed topics never leak |

The assistant does all the thinking — RadioMind just organizes the prompts and stores the results. **Zero extra LLM cost.**

---

## How memory works

A conversation enters RadioMind and flows through layers, just like the brain:

```
Conversation → "I started running, my sleep improved"
     │
     ▼
 ┌─ L1 Attention Gate ──────────────────────────────┐
 │  Extracts: fact about running + sleep             │
 │  Detects: domain = health                         │
 │  Tags: privacy = guarded (health is sensitive)    │
 └───────────────────────────────┬───────────────────┘
                                 ▼
 ┌─ L2 Memory Notes (3D Pyramid) ───────────────────┐
 │  Stores as fact: "running improves sleep"         │
 │  Indexed by: domain × time × abstraction level    │
 │  After 10+ facts → summarizes into patterns       │
 │  After 3+ patterns → distills into principles     │
 └───────────────────────────────┬───────────────────┘
                                 ▼
 ┌─ L3 Habit Memory ────────────────────────────────┐
 │  Three-body debate:                               │
 │    Guardian: "Consistent with what we know"       │
 │    Explorer: "New pattern: exercise → sleep"      │
 │    Reducer:  "Merge with existing health habits"  │
 │  → Encoded as HDC hypervector (10,000-bit)        │
 │  → Periodically baked into LoRA weights           │
 └───────────────────────────────┬───────────────────┘
                                 ▼
 ┌─ L4 External Knowledge ──────────────────────────┐
 │  Shortwave library: curated knowledge from        │
 │  articles, docs, community — "memory reads books" │
 └──────────────────────────────────────────────────┘

 Meta layer (always active):
   User profile: who they are, how they work, what they care about
   Self profile: what model am I using, how many memories, what's my state
```

**Each layer mirrors a brain structure:**

| Brain structure | What it does in the brain | RadioMind layer |
|-------|-------------|-----------------|
| Prefrontal cortex | Holds 5–9 items in focus, decides what's worth encoding, filters out noise from the stream of consciousness | L1 — attention gate: pattern-matches 15+ triggers ("I like...", "remember..."), auto-detects domain, tags privacy |
| Hippocampus | Records experiences rapidly with spatial/temporal context, acts as a fast index that the neocortex can query | L2 — 3D pyramid: SQLite FTS5 indexed by domain × time × abstraction level, attention-style retrieval (principles → patterns → facts) |
| Neocortex | Slowly integrates experiences into generalized knowledge through repeated exposure, forms abstractions independent of specific episodes | L3 — habit memory: three-body debate distills patterns into habits, encoded as HDC 10,000-bit hypervectors, periodically baked into LoRA model weights |
| Sleep (SHY) | Globally downscales synaptic strength, keeping well-used connections and pruning rarely-activated ones, replays important memories | "Dream" refinement: decays memories not accessed in 30+ days, merges redundant entries, free-associates across domains to discover meta-patterns |
| Social conversation | Strengthens memories through retrieval practice and elaborative discussion, creates new connections through debate | "Chat" refinement: three agents with competing goals (consistency, novelty, parsimony) debate and vote, producing insights no single perspective would find |
| Books & culture | Acquires knowledge without direct experience through language and shared narratives | L4 — Shortwave library: curated knowledge ingested from articles and community, enters L2 as facts and walks the same consolidation path as personal experience |

### Deep dive

<details>
<summary><b>Three-body debate — why three roles, not two</b></summary>

Two debaters tend to merge or one dominates. Three debaters with competing interests produce more robust conclusions (ICLR 2025 DMAD: 91% vs 82% accuracy).

```
Guardian (魏) — "Does this fit what we already know?"   → rewards consistency
Explorer (吴) — "Is there something genuinely new?"     → rewards novelty
Reducer  (蜀) — "Can we simplify or merge?"             → rewards parsimony

Vote: 2 out of 3 must agree → candidate insight → verified in future conversations
```

Inspired by Three Kingdoms strategy: two powers merge or one conquers; three powers create lasting balance through mutual checks.

</details>

<details>
<summary><b>LoRA training — memories that don't need retrieval</b></summary>

Periodically, RadioMind fine-tunes a small local model (0.5–3B) on accumulated habits:

```bash
radiomind train --iters 100    # ~5 min on MacBook (Apple MLX)
```

After training, the model "just knows" your preferences — like how you know fire is hot without looking it up. The adapter is a few MB, loads in under a second.

Works on Mac (MLX), Linux (QLoRA/CUDA), or skips gracefully if unavailable.

</details>

<details>
<summary><b>Rust daemon — for 100K+ memories and 24/7 uptime</b></summary>

Storage hot paths run in a Rust daemon for production scale:

```
Python logic layer (LLM calls, prompts, training)
         ↕ Unix socket JSON Lines
Rust daemon (SQLite, FTS5, HDC, knowledge graph, 16 IPC methods)
```

```bash
cd rust-core && cargo build --release
./target/release/radiomind-daemon
```

Python auto-detects the daemon. Falls back to direct SQLite if not running.

</details>

<details>
<summary><b>Privacy levels — some topics stay private</b></summary>

Each domain gets a privacy level:

- **open** — flows freely across domains (default)
- **guarded** — only patterns/principles cross boundaries, not raw facts (auto-applied to health, finance)
- **sealed** — never leaves its domain, ever

Health data that "running helps sleep" can influence work advice as a principle ("regular routines improve performance") without exposing the raw health fact.

</details>

---

## Setup

### Recommended: let your AI agent install it

Copy this prompt to your AI assistant (Claude Code, Cursor, Windsurf, Codex, etc.):

```text
Install RadioMind as my persistent memory module:
1. Run: pip install radiomind
2. Verify: python -c "import radiomind; print(radiomind.__version__)"
3. If I use Claude Desktop or Cursor, also run: claude mcp add radiomind -- radiomind mcp-server
4. Test: python -c "import radiomind; m = radiomind.connect(); m.add([{'role':'user','content':'test'}]); print(m.search('test')); m.close()"

RadioMind auto-detects LLM from environment variables (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.) or local Ollama. No config file needed.
```

### Traditional install

```bash
pip install radiomind

# Optional extras
pip install 'radiomind[server]'      # REST API
pip install 'radiomind[train]'       # LoRA fine-tuning (Apple Silicon)
pip install 'radiomind[embedding]'   # Vector search (ONNX)
```

## Use

```python
import radiomind

mind = radiomind.connect()

# Your agent's conversation loop:
mind.add(messages)                    # feed conversations in
results = mind.search("query")       # get relevant memories back
system_prompt = mind.digest()        # inject user context (~250 tokens)
mind.refine()                        # distill habits (automatic)
```

That's the entire API. Domain detection, privacy tagging, habit encoding, memory pruning — all automatic.

**Works with any LLM — zero config:**

```python
# Pass your existing client — RadioMind auto-detects the type
mind = radiomind.connect(llm=openai_client)
mind = radiomind.connect(llm=anthropic_client)

# Or just have an API key in your environment — RadioMind finds it
# Supports: OpenAI, Anthropic, DashScope, DeepSeek, Groq, Together,
#           Moonshot, Zhipu, SiliconFlow, Mistral, Fireworks, Ollama
```

## Plug into your stack

| Method | One-line setup | Best for |
|--------|---------------|----------|
| **Python** | `radiomind.connect()` | Any Python agent |
| **MCP** | `claude mcp add radiomind -- radiomind mcp-server` | Claude Desktop, Cursor, VS Code |
| **REST** | `radiomind serve --port 8730` | Any language, remote |
| **CLI** | `radiomind search "query"` | Scripts, cron, hooks |

9 MCP tools, 6 REST endpoints, 20+ CLI commands. See [Integration Guide](docs/integration.md).

---

## Research foundations

RadioMind's design draws from established neuroscience and AI research:

**Complementary Learning Systems** (McClelland, McNaughton & O'Reilly, 1995) — The brain uses two systems: the hippocampus for fast, specific learning and the neocortex for slow, generalized knowledge. RadioMind mirrors this with L2 (fast pyramid storage) and L3 (slow habit consolidation).

**Synaptic Homeostasis Hypothesis** (Tononi & Cirelli, 2006) — During sleep, the brain globally downscales synaptic connections, keeping strong ones and pruning weak ones. RadioMind's "dream" refinement does the same: decay unused memories, merge redundant ones, archive stale ones.

**Hyperdimensional Computing** (Kanerva, 2009) — The brain's representations are extremely high-dimensional and distributed. HDC uses 10,000-bit bipolar vectors where binding = association, bundling = superposition. RadioMind encodes habits this way — one fixed-size vector stores an unlimited number of patterns.

**Multi-Agent Debate** (ICLR 2025, DMAD) — Heterogeneous multi-agent debate with diverse foundation models outperforms single-agent and homogeneous teams. RadioMind's three-body debate applies this: three agents with competing objectives (consistency, novelty, parsimony) produce more robust insights than any single perspective.

**LoRA** (Hu et al., 2021) — Low-Rank Adaptation enables efficient model fine-tuning by adding small trainable matrices. RadioMind uses this to "bake" habits into model weights — turning retrieval-dependent knowledge into parametric knowledge (the model just knows, without looking up).

**NeuroDream** (2026) — Introducing an explicit "dream phase" into neural training — where the model disconnects from input and replays stored representations — reduces forgetting by 38% and improves zero-shot transfer by 17.6%. RadioMind's dream refinement follows the same principle.

**Stigmergy** (Grassé, 1959) — Ants coordinate without direct communication by leaving pheromone trails that decay over time. Frequently-used trails grow stronger; abandoned trails fade. RadioMind's community knowledge scoring uses the same model: entries gain strength from usage, decay naturally over time, no human curation needed.

---

## Radio ecosystem

RadioMind is part of a family of tools designed for AI agents that learn and grow:

| Project | What it does | Relationship to RadioMind | Status |
|---------|-------------|---------------------------|--------|
| **[RadioHeader](https://github.com/ZaptainZ/radioheader)** | Cross-project experience framework for coding agents (Claude Code, Codex). Captures debugging experience in one project and applies it in another. | Uses RadioMind as its memory backend. RadioHeader handles rules and behavior contracts ("search before you code"); RadioMind handles storage, retrieval, and habit distillation. | Released, 100+ shortwave entries |
| **RadioMind** | Bionic memory core. Stores, searches, and refines memories into habits. Works standalone or plugs into any agent. | This repo. The "brain" of the ecosystem. | Released |
| **RadioHand** | Personal agent framework. Multi-channel (Telegram, WeChat, Web), task planning, tool orchestration. | Will use RadioMind as its default memory module. RadioHand handles execution ("hands"); RadioMind handles memory ("brain"). | Planned |

```
RadioHeader (rules & experience) → RadioMind (memory & habits) → RadioHand (actions & channels)
         head                              brain                          hands
```

## License

MIT
