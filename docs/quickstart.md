# Quickstart — 5 minutes to your first memory

## Install

```bash
pip install radiomind
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
results = mind.search("exercise")
for r in results:
    print(f"[{r.level}/{r.domain}] {r.content}")
# [fact/health] I like running every morning
```

Search uses pyramid retrieval: principles → patterns → facts, plus HDC habit matching.

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

## Configure LLM (for refinement)

### Option A: Inject from your framework (recommended)

If you already have an LLM in your agent framework, just pass it:

```python
# Any callable with signature (prompt: str, system: str) → str
mind = radiomind.connect(llm=lambda p, s: my_llm.generate(p, system_prompt=s))
mind.refine()  # uses your LLM, no config needed
```

Works with OpenAI, Anthropic, LangChain, or any custom LLM — just wrap it as a callable.

### Option B: RadioMind's own config

Create `~/.radiomind/config.toml`:

```toml
[llm]
default_backend = "openai"

[llm.openai]
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key = "your-key"
model = "qwen-plus"
```

Or use Ollama (local, free):

```toml
[llm]
default_backend = "ollama"

[llm.ollama]
host = "http://localhost:11434"
model = "qwen3:0.6b"
```

## CLI alternative

Everything above works from the command line too:

```bash
radiomind init
echo '{"role":"user","content":"I like running"}' | radiomind ingest /dev/stdin
radiomind search "exercise"
radiomind status
```

## Next: Integration

See [integration.md](integration.md) for connecting RadioMind to Claude, Hermes, or your own agent.
