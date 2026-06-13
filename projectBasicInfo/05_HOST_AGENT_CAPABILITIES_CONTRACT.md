# 05 — Host Agent Capabilities & Authorization Contract

> Date: 2026-06-13 | Author: cc | Status: **contract draft, no runtime changes**
> Scope: PersonalOnboarding-1b. Defines what a host agent (Hermes / OpenClaw /
> future RadioHand) must declare, which side effects require user
> authorization, and how RadioMind runs conservatively when nothing is
> authorized. Interface/product contract only — not an implementation.
> Out of scope: subscriptions, managed retrieval, RadioHeader repo, asking
> ordinary users for an API key.

## 0. Why this exists

PersonalOnboarding-1a found the dangerous gap is not missing features — it is
that the Hermes provider's background side effects are **ON by default**
(auto-ingest every turn, auto-refine every 10 turns, auto-dream on session
end). That contradicts the product principle (04 §1.4): *every side effect
needs host-mediated authorization*. A contract must fix the **defaults** and
the **capability/authorization shape** before any code, or the implementation
will silently re-introduce "install → it just starts writing/dreaming".

**Governing rule:** *Absence of a declared capability or authorization means
the conservative behavior, never the permissive one.* RadioMind must be safe
and useful (add/search/digest still work locally) without any host capability
or grant.

## 1. HostCapabilities (draft)

A pure declaration the host passes at init. Fields **describe ability only —
they never perform an action**. All default to the conservative value (no
capability) so an unset field is never read as "allowed".

```python
@dataclass(frozen=True)
class HostCapabilities:
    host_name: str = "unknown"
    host_kind: str = "unknown"        # personal_agent | programming_agent | power_user | unknown

    # LLM
    has_host_llm: bool = False        # host has *some* LLM it could lend
    llm_call_available: bool = False  # a working (prompt, system)->str callable is wired now

    # User interaction
    can_prompt_user: bool = False     # host can show an authorization prompt and return the answer

    # Data access (ability, not permission — permission is AuthorizationScopes)
    can_import_memory: bool = False
    can_read_chat_history: bool = False
    can_read_files: bool = False

    # Background execution
    supports_background_hooks: bool = False
    supports_scheduled_tasks: bool = False

    # Retrieval
    has_embedding_provider: bool = False
    has_vector_store: bool = False

    # Misc host services
    can_open_external_url: bool = False
    can_store_persistent_config: bool = False
```

Notes:
- `has_host_llm` vs `llm_call_available`: a host may *have* an LLM but not have
  wired the callable yet — onboarding can then ask the host to wire it, without
  ever asking the end user for a key.
- `has_embedding_provider` / `has_vector_store` let the host offer retrieval;
  absent → RadioMind uses local FTS (managed retrieval stays deferred).

## 2. AuthorizationScopes (draft)

Every side effect maps to a scope the host must grant (via `can_prompt_user`)
before RadioMind performs it. A scope is **not granted by enabling the
provider** — enabling the provider only grants local read-side memory
(add/search/digest of data the host already hands over for the current turn is
covered by `ingest_new_turns`, see below; even that is opt-in).

| Scope | Trigger | Authorization prompt (key points) | Unauthorized fallback | Revocable |
|---|---|---|---|---|
| `import_existing_memory` | onboarding finds prior Hermes/OpenClaw memory | "Import N existing memories into RadioMind?" — says source + count | skip import; store starts empty | yes |
| `ingest_new_turns` | each conversation turn | "Let RadioMind remember this conversation?" (one-time per session/agent) | **no auto-write**; only explicit `learn`/tool calls persist | yes |
| `write_long_term_memory` | promoting facts → patterns/principles/habits | "Allow RadioMind to build long-term habits from your memories?" | facts stay L0/L2 only; no consolidation | yes |
| `background_refinement` | periodic three-body `trigger_chat` | "Run background refinement to distill habits?" | **no auto trigger_chat**; only manual `refine` | yes |
| `dream_after_session` | `on_session_end` dream/prune | "Run a 'dream' pass to prune/merge memory after sessions?" | **no auto dream**; manual `dream` only | yes |
| `train_lora` | `train` / `deploy` | "Train a personal adapter from your habits? (uses local compute)" | blocked; CLI opt-in path unchanged | yes |
| `call_external_llm` | any LLM call to a non-host endpoint (user key / config) | "Allow calls to <provider>? Text leaves your machine." | host LLM only; else pure-memory mode | yes |
| `call_external_embedding` | remote embedder (e.g. DashScope) | "Allow embedding via <provider>? Text leaves your machine." | local FTS only | yes |
| `export_or_upload_memory` | any memory leaving the machine | "Export/upload memory to <target>?" | blocked | yes |
| `enable_background_hooks` | installing persistent host hooks | "Install background hooks so RadioMind runs between sessions?" | no persistent hooks; in-session only | yes |

Principle: **deny-by-default**. An ungranted scope yields the fallback, never
the action. Scopes are independent (granting ingest does not grant dream).

## 3. Current Hermes provider behavior — compliance mapping

From PersonalOnboarding-1a (src/radiomind/adapters/hermes.py):

| Current behavior | Required authorization | Proposed default (no grant) | Fallback |
|---|---|---|---|
| `sync_turn` auto-ingests every turn (background thread) | `ingest_new_turns` | **OFF** (no auto-write) | persist only via explicit `learn`/tool call |
| `sync_turn` triggers `trigger_chat` every 10 turns | `background_refinement` | **OFF** | manual `refine` only |
| `on_session_end` auto-dreams (`_auto_dream=True`) | `dream_after_session` | **OFF** (flip default to False) | manual `dream` only |
| `on_memory_write` mirrors host memory via `learn` | `import_existing_memory` (mirror = ongoing import) | **OFF** unless granted | host memory not mirrored |
| Auto DashScope embedder when config has a key | `call_external_embedding` | **OFF** unless granted | local FTS |
| Provider exposes 4 tools (search/learn/habits/status) | — (read/limited) | unchanged | — (but see gap below) |

**Gap:** provider tool set (4) ≪ MCP tool set (17): personal agents via the
provider cannot reach ingest/digest/delete/history. 1c may widen the provider
tool set, but **only read-side + explicitly-authorized write tools** — not the
background auto-writes.

**The single most important change:** the three auto-background behaviors
(ingest / refine / dream) must become **no-ops until their scope is granted**.
Today enabling the provider silently starts all three.

## 4. Initialization flow (draft)

Host, after selecting RadioMind as memory provider, runs in order:

1. **detect** — build `HostCapabilities`.
2. **explain** — tell the user what RadioMind can do (memory/search/digest now;
   habits/dream/LoRA opt-in).
3. **ask import** — if `can_import_memory` and prior memory exists, request
   `import_existing_memory`.
4. **import** — only if authorized; produce a formatted import text → `ingest`.
5. **configure LLM** — host LLM first (`llm_call_available`); if absent, do
   **not** ask an ordinary user for a key — surface "refinement/train need an
   LLM" as an advanced option only.
6. **check retrieval** — `has_embedding_provider`/`has_vector_store` → host
   retrieval; else local FTS. Managed retrieval = future, not offered here.
7. **readiness report** — emit §5.
8. **suggest advanced** — only when preconditions met (e.g. "enough data +
   train scope → you could train a personal adapter").

Ordinary users are never asked for an API key; no generic LLM subscription is
offered; vector subscription is deferred to last (04 §1.3 / §5).

## 5. ReadinessReport (draft)

What onboarding shows the host/user after init. Pure data, no side effects.

```python
@dataclass
class ReadinessReport:
    memory_import: str        # ready | skipped | blocked
    host_llm: str             # ready | missing | degraded
    retrieval: str            # local_ready | fts_only | external_needed
    background_hooks: str     # authorized | not_authorized | unsupported
    lora: str                 # ready | needs_more_data | disabled
    privacy_status: str       # local_only | external_calls_authorized | export_authorized
    recommended_next_action: str
```

`privacy_status` defaults to `local_only` and only escalates when an
external-call scope is granted — so the report doubles as a privacy ledger.

## 6. PersonalOnboarding-1c — minimal implementation advice

Keep the first cut **very narrow**:

1. Provider accepts `HostCapabilities` + granted `AuthorizationScopes` at
   `initialize(...)` (additive kwargs; absent = conservative).
2. **Flip the three background defaults to OFF**: `sync_turn` auto-ingest,
   10-turn `trigger_chat`, `on_session_end` dream all become no-ops unless the
   matching scope is granted. (`_auto_dream` default False.)
3. Add a **pure `readiness_report()` function** returning §5.
4. **Unit tests first on the conservative defaults**: provider with no
   capabilities/scopes performs NO background ingest/refine/dream; with scopes
   granted, the existing behavior resumes.

Do **not** in 1c: build a memory-import UI, widen subscriptions, add managed
retrieval, change the resolution chain, or touch the RadioHeader repo. Tool-set
widening (§3 gap) and import discovery are later, separately-scoped steps.

## 7. Done criteria for 1b (this doc)

- ✅ A personal agent can read which capabilities it must declare (§1).
- ✅ Every authorization-requiring action is enumerated with fallback (§2).
- ✅ The exact places current Hermes defaults are non-compliant are mapped (§3).
- ✅ PersonalOnboarding-1c has a narrow, test-first implementation scope (§6).
