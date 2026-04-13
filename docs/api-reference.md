# API Reference

## Layer 1: Simple API (4 methods)

The recommended interface for most users. Import `radiomind.connect()` and you're done.

```python
import radiomind
mind = radiomind.connect()
```

### `mind.add(messages, user_id="") → AddResult`

Add conversation messages to memory.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `messages` | `list[dict]` | required | `[{"role": "user", "content": "..."}]` |
| `user_id` | `str` | `""` | Optional user identifier |

**Returns:** `AddResult(added=int, skipped=int)`

```python
result = mind.add([
    {"role": "user", "content": "I like running"},
    {"role": "assistant", "content": "Running is great!"},
])
```

### `mind.search(query, limit=10, domain=None) → list[Memory]`

Search memories using pyramid retrieval + HDC habit matching.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | required | Search query (Chinese or English) |
| `limit` | `int` | `10` | Maximum results |
| `domain` | `str\|None` | `None` | Filter by domain |

**Returns:** `list[Memory]` where `Memory(content, domain, level, score, metadata)`

```python
results = mind.search("exercise", limit=5)
for r in results:
    print(f"[{r.level}/{r.domain}] {r.content} (score={r.score:.2f})")
```

### `mind.digest(token_budget=250) → str`

Generate a context digest for system prompt injection.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `token_budget` | `int` | `250` | Approximate token limit |

**Returns:** Compressed string with user profile + active domains + system state.

```python
system_prompt = f"You are a helpful assistant.\n\n{mind.digest()}"
```

### `mind.refine(domain=None) → RefineResult`

Run a full refinement cycle: three-body debate + dream pruning.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `domain` | `str\|None` | `None` | Focus domain (None = all) |

**Returns:** `RefineResult(insights, merged, pruned, duration_s)`

Requires an LLM backend configured in `~/.radiomind/config.toml`.

### `mind.close()`

Shut down RadioMind and release resources.

### `mind.advanced → RadioMind`

Access the full Layer 3 API for power users.

---

## Layer 2: Protocol

The formal interface contract. Any memory backend implementing this Protocol is a valid RadioMind provider.

```python
from radiomind import MemoryProtocol

def my_agent(memory: MemoryProtocol):
    memory.add([{"role": "user", "content": "..."}])
    results = memory.search("query")
```

Use this for type hints in your agent code — it decouples your agent from RadioMind internals.

---

## Layer 3: Advanced API (`RadioMind` class)

Full control over all subsystems. Access via `mind.advanced` from Simple API, or directly:

```python
from radiomind import RadioMind
mind = RadioMind()
mind.initialize()
```

### Memory Operations

| Method | Description |
|--------|-------------|
| `ingest(messages)` | L1 attention gate → L2 storage |
| `search(query, domain)` | FTS5 + LIKE search |
| `search_pyramid(query)` | Pyramid: principles → patterns → facts |
| `query_habits(query)` | L3 HDC habit matching |
| `learn(text)` | Add L4 external knowledge |

### Refinement

| Method | Description |
|--------|-------------|
| `trigger_chat(domain)` | Three-body debate (Guardian/Explorer/Reducer) |
| `trigger_dream()` | SHY pruning + DMN wandering |

### Meta

| Method | Description |
|--------|-------------|
| `get_user_profile()` | WHO/HOW/WHAT about the user |
| `get_self_profile()` | IDENTITY/STATE/CAPABILITY of the system |
| `get_context_digest(budget)` | Compressed digest for system prompts |

### Training

| Method | Description |
|--------|-------------|
| `generate_training_data()` | Habits + memories → JSONL |
| `train(iters, model)` | MLX LoRA fine-tuning |

### Stats & Config

| Method | Description |
|--------|-------------|
| `stats()` | Full memory statistics |
| `update_config(key, value)` | Modify configuration |

---

## REST API

Start with `radiomind serve --port 8730`. OpenAPI docs at `/docs`.

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| POST | `/v1/add` | `{"messages": [...]}` | `{"added": N, "skipped": N}` |
| POST | `/v1/search` | `{"query": "...", "limit": 10}` | `{"results": [...]}` |
| GET | `/v1/digest` | `?token_budget=250` | `{"digest": "..."}` |
| POST | `/v1/refine` | `{"domain": null}` | `{"insights": N, ...}` |
| GET | `/v1/status` | — | `{"total_active": N, ...}` |
| GET | `/health` | — | `{"status": "ok"}` |

Auth: `Authorization: Bearer <token>` (optional, set in config.toml).

---

## MCP Tools

Start with `radiomind mcp-server`. 8 tools for Claude Desktop/Cursor/VS Code.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `radiomind_search` | `query, domain?` | Pyramid search |
| `radiomind_ingest` | `messages[]` | Ingest conversation |
| `radiomind_learn` | `text` | Add external knowledge |
| `radiomind_habits` | `query` | Query HDC habits |
| `radiomind_digest` | `token_budget?` | Context digest |
| `radiomind_status` | — | Memory statistics |
| `radiomind_chat` | `domain?` | Three-body debate |
| `radiomind_dream` | — | Dream refinement |

---

## Data Types

```python
from radiomind import Memory, AddResult, RefineResult

# Memory — a search result
Memory(content="...", domain="health", level="fact", score=0.85, metadata={})

# AddResult — from add()
AddResult(added=3, skipped=1)

# RefineResult — from refine()
RefineResult(insights=2, merged=1, pruned=3, duration_s=12.5)
```
