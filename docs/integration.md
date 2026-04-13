# Integration Guide

RadioMind provides 5 integration methods. Pick the one that fits your stack.

## Method 1: Python API (simplest)

For Python agents, frameworks, or scripts.

```python
import radiomind

mind = radiomind.connect()
mind.add(messages)
results = mind.search("query")
digest = mind.digest()
mind.close()
```

**When to use:** Your agent is Python, runs in the same process.

### With LangChain

```python
import radiomind
from langchain.agents import AgentExecutor

mind = radiomind.connect()

# Inject digest into system prompt
system = f"You are a helpful assistant.\n\nUser context:\n{mind.digest()}"

# After each conversation turn
mind.add([{"role": "user", "content": user_input},
          {"role": "assistant", "content": response}])
```

### With any Python agent

```python
import radiomind
from radiomind import MemoryProtocol  # type hint for your agent

class MyAgent:
    def __init__(self, memory: MemoryProtocol):
        self.memory = memory
    
    def respond(self, user_input: str) -> str:
        # Search memories for context
        memories = self.memory.search(user_input)
        context = "\n".join(m.content for m in memories[:3])
        
        # Your LLM call here
        response = call_llm(user_input, context=context)
        
        # Save to memory
        self.memory.add([
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": response},
        ])
        return response

agent = MyAgent(memory=radiomind.connect())
```

---

## Method 2: REST API (any language)

For non-Python frameworks, remote access, or microservices.

### Setup

```bash
pip install 'radiomind[server]'
radiomind serve --port 8730
```

API docs auto-generated at `http://localhost:8730/docs` (Swagger UI).

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/add` | Add conversation messages |
| POST | `/v1/search` | Search memories |
| GET | `/v1/digest` | Get context digest |
| POST | `/v1/refine` | Run refinement cycle |
| GET | `/v1/status` | Memory statistics |
| GET | `/health` | Health check |

### Examples

**Add memories:**
```bash
curl -X POST http://localhost:8730/v1/add \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "I like running"}]}'
# → {"added": 1, "skipped": 0}
```

**Search:**
```bash
curl -X POST http://localhost:8730/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "exercise", "limit": 5}'
# → {"query": "exercise", "count": 1, "results": [...]}
```

**Digest:**
```bash
curl http://localhost:8730/v1/digest?token_budget=250
# → {"digest": "User: name: Alice\nStyle: ...", "token_budget": 250}
```

### Authentication (optional)

Add to `~/.radiomind/config.toml`:
```toml
[server]
auth_token = "your-secret-token"
```

Then include in requests:
```bash
curl -H "Authorization: Bearer your-secret-token" ...
```

### JavaScript/TypeScript

```typescript
const response = await fetch("http://localhost:8730/v1/search", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: "exercise", limit: 5 }),
});
const { results } = await response.json();
```

### Go

```go
body := `{"query": "exercise", "limit": 5}`
resp, _ := http.Post("http://localhost:8730/v1/search", "application/json", strings.NewReader(body))
```

---

## Method 3: MCP Server (Claude Desktop / Cursor / VS Code)

For AI-native editors and assistants that support MCP.

### Setup

```bash
# One command — Claude Desktop auto-discovers it
claude mcp add radiomind -- radiomind mcp-server
```

Or add to Claude Desktop config manually:
```json
{
  "mcpServers": {
    "radiomind": {
      "command": "radiomind",
      "args": ["mcp-server"]
    }
  }
}
```

### Available tools (8)

| Tool | Description |
|------|-------------|
| `radiomind_search` | Pyramid search (principles → patterns → facts) |
| `radiomind_ingest` | Ingest conversation messages |
| `radiomind_learn` | Add external knowledge |
| `radiomind_habits` | Query L3 habit memories |
| `radiomind_digest` | Get context digest |
| `radiomind_status` | Memory statistics |
| `radiomind_chat` | Trigger three-body debate |
| `radiomind_dream` | Trigger dream refinement |

The AI assistant automatically calls these tools during conversation.

---

## Method 4: Hermes Agent Memory Provider

For [Hermes Agent](https://hermes-agent.nousresearch.com/) users.

### Setup

```bash
pip install radiomind
hermes config set memory.provider radiomind
```

Or interactive:
```bash
hermes memory setup  # select "radiomind"
```

### What happens automatically

- **`system_prompt_block()`**: RadioMind injects context digest into every turn
- **`prefetch(query)`**: Searches memories before each API call
- **`sync_turn(user, assistant)`**: Ingests every conversation turn (non-blocking)
- **`on_session_end()`**: Runs dream refinement when you close the session
- **`on_memory_write()`**: Mirrors Hermes MEMORY.md changes to RadioMind

### Provider tools

4 tools available in Hermes: `radiomind_search`, `radiomind_learn`, `radiomind_habits`, `radiomind_status`.

---

## Method 5: RadioHeader Bridge

For [RadioHeader](https://github.com/ZaptainZ/radioheader) users — migrate existing cross-project experience into RadioMind.

### Migrate existing data

```bash
radiomind migrate-radioheader
# → Topics: 480, Shortwave: 241, Projects: 13 imported
```

### Use RadioMind as search backend

```bash
radiomind rh-search "白屏"     # RadioHeader-compatible JSON output
radiomind rh-consolidate       # Runs dream + writes context-digest.md
```

### Community sharing

```bash
radiomind community sync       # Import from RadioHeader community pool
radiomind community contribute # Share insights (PII-filtered)
```

---

## Method 6: CLI / Shell scripts

For automation, cron jobs, or shell-based workflows.

```bash
# Ingest from JSONL file
radiomind ingest conversations.jsonl

# Search
radiomind search "keyword"

# Status
radiomind status

# Scheduled refinement (add to crontab)
# Run dream refinement every night at 3am
0 3 * * * radiomind dream

# Run chat refinement every 6 hours
0 */6 * * * radiomind chat
```

---

## Choosing the right method

| Your situation | Use | Setup time |
|---------------|-----|-----------|
| Python agent, same process | Python API | 1 minute |
| Non-Python, or remote access | REST API | 2 minutes |
| Claude Desktop / Cursor | MCP Server | 1 minute |
| Hermes Agent | Memory Provider | 1 minute |
| Existing RadioHeader user | Bridge | 1 minute |
| Cron / shell automation | CLI | 1 minute |
