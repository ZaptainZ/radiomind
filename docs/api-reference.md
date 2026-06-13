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

## CLI command reference

Every command works as `radiomind <cmd>` or `python -m radiomind <cmd>`.
Side-effect class tells you what a command touches before you run it.

| Command | Purpose | Side-effect class | Needs LLM |
|---|---|---|---|
| `init` | create the data directory | writes-local (no config file) | — |
| `onboard` | first-run route/config guidance; optional config template writer | read-only by default; writes-config with `--write-config-template` | — |
| `doctor` | health check (deps, LLM, integration) | read-only | — |
| `status` | memory/habit/domain stats | read-only | — |
| `config [key] [value]` | view or set config | writes-config | — |
| `search <query>` | pyramid + habit search | read-only | optional |
| `ingest <file.jsonl>` | ingest conversation turns | writes-local | optional |
| `learn <text>` | add external knowledge | writes-local | — |
| `chat [-d domain]` | three-body refinement | writes-local + calls-LLM | ✅ |
| `dream` | SHY prune + DMN wander | writes-local + calls-LLM | ✅ |
| `refine-step <step>` | host-driven refinement step | writes-local | host |
| `train [--prepare-habits]` | LoRA fine-tune (opt-in: `RADIOMIND_ENABLE_LORA=1`) | trains-deploys | ✅ |
| `deploy` | fuse + GGUF + register with Ollama (opt-in) | trains-deploys + external | — |
| `serve [--port]` | REST server | starts-server | per call |
| `mcp-server` | MCP stdio server | starts-server | per call |
| `setup` / `setup-restore` | install / restore host hooks (backed up) | writes-host | — |
| `embed-backfill` | backfill vectors | writes-local + calls-embedding | — |
| `push-habits` | push habits to host native memory | writes-host | — |
| `learn` / `migrate-radioheader` / `rh-search` / `rh-consolidate` | RadioHeader bridge | mixed | — |

Side-effect classes: **read-only** (safe) · **writes-local** (local store) ·
**writes-config / writes-host** · **calls-LLM / calls-embedding** (text may leave
the machine if the backend is remote) · **trains-deploys** · **starts-server**.

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

Start with `radiomind mcp-server` (stdio) for Claude Desktop / Cursor / VS Code.
The full tool surface (as of 2026-06-13) — grouped by capability. `LLM` = the
call needs an LLM backend; `writes` = it writes the local memory store.

**Retrieval / read**
| Tool | Purpose | LLM | writes |
|---|---|---|---|
| `radiomind_search` | pyramid search (principles→patterns→facts) + HDC habits | — | — |
| `radiomind_habits` | query L3 habit memories | — | — |
| `radiomind_digest` | compressed user-context digest for system-prompt injection | — | — |
| `radiomind_status` | memory stats (levels, domains, habits, LLM usage) | — | — |
| `radiomind_get_memory` | fetch one memory by id | — | — |
| `radiomind_list_memories` | list by scope (user/agent/session) | — | — |
| `radiomind_memory_history` | audit trail for a memory | — | — |

**Memory write**
| Tool | Purpose | LLM | writes |
|---|---|---|---|
| `radiomind_ingest` | ingest a conversation (extract facts, detect domains) | optional | ✅ |
| `radiomind_learn` | add external knowledge into L2 facts | — | ✅ |
| `radiomind_update_memory` | edit content/metadata (audited) | — | ✅ |
| `radiomind_delete_memory` | delete one memory by id (audited) | — | ✅ |
| `radiomind_delete_scope` | delete ALL memories in a scope (audited) | — | ✅ |

**Refinement**
| Tool | Purpose | LLM | writes |
|---|---|---|---|
| `radiomind_chat` | three-body debate → distilled insights | ✅ | ✅ |
| `radiomind_dream` | SHY pruning + DMN wandering | ✅ | ✅ |
| `radiomind_refine_step` | host-driven step refinement (host AI does the thinking) | host | ✅ |

**Habits → host**
| Tool | Purpose | LLM | writes |
|---|---|---|---|
| `radiomind_push_habits` | push confirmed habits to the host's native memory | — | host files |
| `radiomind_reject_habit` | mark a habit incorrect / not applicable | — | ✅ |

> **Front-stage vs background.** These MCP tools are explicit
> client/user-initiated calls (like CLI commands), so they are **not** gated by
> the Hermes provider's authorization scopes — that gating applies only to the
> provider's *automatic background* side effects (auto-ingest per turn,
> background refinement, dream-after-session). Tools marked `writes`/`LLM`
> still touch the local store or call an LLM when invoked — see the columns.
>
> LoRA `train` / `deploy` are **CLI-only** (`radiomind train` / `deploy`), not
> exposed over MCP.

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
