# Quickstart — 5 minutes to your first memory

> **Coding-agent user?** (Claude Code / Codex / Cursor / Windsurf) install
> **[RadioHeader](https://github.com/ZaptainZ/radioheader)** instead — it uses
> RadioMind as its backend. This quickstart is for personal-agent and
> power-user use of the engine directly.

> The 5-minute path is **install → add → search → digest**. Training a
> personal LoRA adapter is an opt-in advanced path (more data + the MLX
> extra + time) — see [Advanced: cold-start to a personal LoRA](#advanced-cold-start-to-a-personal-lora).

## Install

```bash
pip install radiomind
```

Two equivalent entry points after install:

```bash
radiomind --help            # console script (when it's on your PATH)
python -m radiomind --help  # always works — use this if PATH is unset (common inside a venv)
```

## Step 1: Connect (1 line)

```python
import radiomind
mind = radiomind.connect()
```

That's it. RadioMind is running. Data lives in `~/.radiomind/`.

## Step 2: Add memories (from conversations)

```python
mind.add([
    {"role": "user", "content": "My name is Alice"},
    {"role": "assistant", "content": "Nice to meet you, Alice!"},
    {"role": "user", "content": "I like running every morning"},
    {"role": "user", "content": "I hate working overtime"},
])
# → AddResult(added=3, skipped=0)
```

RadioMind automatically:
- Extracts memory-worthy content (ignores greetings/noise)
- Detects domains (health, work, learning...)
- Tags privacy levels (health → guarded by default)
- Builds user profile (name, preferences, goals)

## Step 3: Search

```python
results = mind.search("running")     # keyword match — works out of the box
for r in results:
    print(f"[{r.level}/{r.domain}] {r.content}")
# [fact/...] I like running every morning
```

Search uses pyramid retrieval: principles → patterns → facts, plus HDC habit matching.

> Out of the box, search is keyword (FTS) — use words that appear in the memory.
> For semantic recall (e.g. matching `"exercise"` to `"running"`), install the
> embedding extra: `pip install 'radiomind[embedding]'`.

## Step 4: Get context digest

```python
digest = mind.digest()
print(digest)
# User: name: Alice
# Style: likes morning running
# Memory: 3 entries across health, work
```

Inject this into your agent's system prompt — it's ~250 tokens of compressed user context.

## Step 5: Refine (optional, needs LLM)

```python
result = mind.refine()
print(f"Insights: {result.insights}, Merged: {result.merged}")
```

This runs the three-body debate + dream pruning cycle. Requires Ollama or an OpenAI-compatible API configured in `~/.radiomind/config.toml`.

## Step 6: Close

```python
mind.close()
```

Or use as context manager:

```python
with radiomind.connect() as mind:
    mind.add(messages)
    results = mind.search("query")
```

## LLM — usually you don't need to do anything

RadioMind **automatically finds** whatever LLM is available. Priority:

| Priority | Source | Example |
|----------|--------|---------|
| 1 | Host framework passes `llm=` | `radiomind.connect(llm=openai_client)` |
| 2 | Environment variable | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DASHSCOPE_API_KEY`, ... |
| 3 | Local Ollama | Just have Ollama running |
| 4 | `~/.radiomind/config.toml` | Advanced override (most users never need this) |
| 5 | No LLM | Pure memory mode — add/search/digest still work |

### Most common: your framework already has an LLM

```python
# OpenAI client → RadioMind auto-detects it
mind = radiomind.connect(llm=openai_client)

# Anthropic client → auto-detected
mind = radiomind.connect(llm=anthropic_client)

# Any callable → just works
mind = radiomind.connect(llm=lambda p, s: my_llm(p, system=s))
```

### Second most common: you have an API key in your environment

```bash
export DASHSCOPE_API_KEY=sk-...   # or OPENAI_API_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, ...
```

RadioMind finds it automatically.

> **What "zero config" really means:** you still need *one* of — a host
> framework LLM (`connect(llm=...)`), an API-key environment variable, or a
> local Ollama with a model pulled. With any of those, no config file is
> needed. `radiomind init` does **not** write a config file or supply a key,
> so a fresh install with none of the above runs in pure-memory mode
> (add/search/digest work; refine/train do not until an LLM is reachable).

### Advanced: manual config (per-provider profiles)

Write `~/.radiomind/config.toml` when you want explicit provider profiles or
cost tiers. Each `[llm.<name>]` section with `base_url` + `api_key` becomes a
selectable backend; `default_backend` picks the one used by default.

```toml
# ~/.radiomind/config.toml
[llm]
default_backend = "dashscope"        # the cost-efficient default

[llm.dashscope]                      # answer / refinement model
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key  = "sk-..."
model    = "deepseek-v3.2"
timeout  = 120                       # refinement generations can be long

[llm.openrouter]                     # optional: e.g. a gpt-4o judge for benchmarks
base_url = "https://openrouter.ai/api/v1"
api_key  = "sk-or-..."
model    = "gpt-4o"

# [llm.openai] is OPTIONAL and not the default. Only add it if you actually
# have an OpenAI-compatible endpoint; an empty/unreachable one is skipped.
```

You can also set keys without editing the file:

```bash
radiomind config llm.default_backend dashscope
```

## CLI alternative

Everything above works from the command line too (use `radiomind` or
`python -m radiomind` interchangeably):

```bash
radiomind init
radiomind onboard                     # first-run route/config guidance
radiomind ingest conversation.jsonl   # one {"role","content"} JSON object per line
radiomind search "running"            # keyword match (FTS); add [embedding] for semantic
radiomind status
radiomind doctor                      # health check — flags any missing dependency
```

## Advanced: cold-start to a personal LoRA

**Opt-in, not part of the 5-minute path.** This bakes your habits into a
small adapter. It needs an LLM reachable (above), the training extra
(`pip install 'radiomind[train]'`, Apple Silicon MLX), and enough data.

```bash
export RADIOMIND_ENABLE_LORA=1        # the LoRA path is gated/opt-in
radiomind ingest my_history.jsonl     # 20-30+ first-person statements help
radiomind train --prepare-habits --data-only   # mint habits + build train.jsonl, no training yet
```

Training data is produced only when all three thresholds are met:

| Requirement | Why |
|---|---|
| **≥ 5 habits** | enough distinct durable patterns |
| **≥ 30 examples** | enough to fine-tune without memorizing |
| **≥ 2 domains** *(or 1 diverse domain)* | breadth; a single diverse domain trains a **narrow adapter** (fits that one topic, flagged `narrow_adapter`) |

If it refuses, the CLI prints the exact gap (e.g. `habits 3/5`, `examples
18/30`) and the next step — add more memories across different topics. When
it passes:

```bash
radiomind train          # fine-tune the adapter (minutes, MLX)
radiomind deploy         # fuse + GGUF + register with Ollama
```

`train --prepare-habits` auto-mints habits from your largest domains when the
store is short on fuel; `radiomind doctor` and `radiomind status` show habit
and domain counts so you can see where you stand.

## Next: Integration

See [integration.md](integration.md) for connecting RadioMind to Claude, Hermes, or your own agent.
