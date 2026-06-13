# 04 — Product Onboarding Implementation Plan

> Date: 2026-06-13  
> Status: implementation guidance, no runtime changes.  
> Scope: RadioMind product entry points, host capability negotiation, and
> authorization model. This document does not define benchmark work.

## 0. Product Decision

RadioMind should not present every user with the same setup path.

There are three product surfaces:

| User type | Recommended entry | RadioMind role |
|---|---|---|
| Personal agent users: Hermes / OpenClaw / future RadioHand | RadioMind memory provider | Memory engine for long-term personal context |
| Programming-agent users: Codex / Claude Code / Cursor | **RadioHeader** | RadioMind is the storage/retrieval backend behind RadioHeader's project-experience layer |
| Power users: Python / CLI / MCP | RadioMind native API | Direct control over storage, search, refine, dream, train, deploy |

This means: **programming agents should be told to use RadioHeader first, not
raw RadioMind.** RadioHeader owns project rules, Echo, cross-project experience,
AGENTS/CLAUDE routing, and "search before coding" behavior. RadioMind should
stay the memory engine under that behavior layer.

## 1. Non-Negotiable Product Principles

### 1.1 Host LLM first

RadioMind should use the host agent's LLM whenever possible.

Priority:

1. Host-supplied LLM callable / SDK client.
2. Host-mediated LLM delegation protocol.
3. User's own API key / local Ollama.
4. RadioMind-provided LLM service: **not in v1**.

For ordinary users, onboarding should not start by asking for a generic LLM API
key. It should first ask the host agent what it can provide.

### 1.2 No generic LLM subscription in the current product plan

Do not design a general "RadioMind LLM subscription" now.

Reasons:

- Personal agents and RadioHeader often already have a strong host LLM.
- General LLM routing introduces privacy, cost, provider, and prompt-governance
  complexity.
- The current product gap is onboarding and retrieval quality, not "sell users
  another chat model."

### 1.3 Managed vector/retrieval subscription is deferred

Managed embedding/rerank is the plausible paid service, but it should be solved
last.

Current stance:

- Default: local/FTS or host/user-provided retrieval capability.
- Later: RadioMind Managed Retrieval may provide embedding + rerank.
- It must be opt-in, permissioned, and privacy-labeled because text leaves the
  user's machine.

### 1.4 Every side effect needs host-mediated authorization

RadioMind can proactively recommend actions, but the host must ask the user
before side effects:

- importing prior memory;
- reading project logs / workspace files;
- writing config, hooks, MCP settings, AGENTS/CLAUDE files;
- calling external LLM / embedding / rerank services;
- training or deploying LoRA;
- running dream/refinement over sensitive memory;
- deleting, merging, or archiving memory.

## 2. Personal Agent Path

Targets: Hermes, OpenClaw, future RadioHand, HomeGenie-style personal agents.

### 2.1 Desired user experience

After installing/selecting RadioMind as the memory provider, the host agent
should guide the user through initialization:

1. Detect host capabilities:
   - Does the host provide an LLM?
   - Can it call tools?
   - Can it persist files?
   - Does it have prior memory to import?
   - Does it support explicit user authorization prompts?
2. Ask for memory import permission:
   - "I found existing Hermes/OpenClaw/RadioHand memory. Import it into
     RadioMind?"
3. Configure maximum available capability:
   - use host LLM if available;
   - enable local/host retrieval if available;
   - leave managed retrieval as future opt-in;
   - do not ask for a generic LLM key unless host has no LLM and user asks for
     refinement/train.
4. Emit readiness report:
   - base memory: enabled/disabled;
   - search: FTS / local embedding / host retrieval / managed retrieval;
   - LLM refinement: host / user key / unavailable;
   - dream: available/unavailable;
   - LoRA: supported / opt-in / blocked with reason.

### 2.2 Implementation phases

**PersonalOnboarding-1a — read-only audit**

- Inventory the existing Hermes provider, MCP server, and integration docs.
- Identify whether a host LLM callable is already available in each path.
- Identify where old memory import can be discovered.
- No code changes.

**PersonalOnboarding-1b — host capability contract**

Define a small data contract:

```python
HostCapabilities(
    host_name: str,
    can_provide_llm: bool,
    can_prompt_user: bool,
    can_import_memory: bool,
    can_write_config: bool,
    supports_background_hooks: bool,
)
```

No subscription logic. No managed retrieval.

**PersonalOnboarding-1c — readiness report**

Add a pure report function that renders:

- enabled capabilities;
- missing capabilities;
- exact next authorization prompt.

The report should be usable by Hermes/OpenClaw/RadioHand without changing the
core memory engine.

## 3. RadioHeader Path For Programming Agents

Targets: Codex, Claude Code, Cursor, Windsurf, project-local coding agents.

### 3.1 Product boundary

Programming agents should not be told "install raw RadioMind" as the primary
path.

Recommended message:

> If you use Codex / Claude Code / Cursor for coding projects, install
> RadioHeader. RadioHeader uses RadioMind as its persistent memory backend.

Why:

- RadioHeader owns project-specific behavior contracts:
  - search prior experience before debugging;
  - Echo lessons after tasks;
  - write project logs;
  - update project overview;
  - maintain project registry and attention weights.
- RadioMind owns storage/search/refinement/habits/LoRA.

### 3.2 Implementation phases

**RadioHeaderMind-1a — doc-only positioning**

Update public docs to route users:

| Situation | Install |
|---|---|
| Coding agent / project experience | RadioHeader |
| Personal agent memory | RadioMind |
| Power-user memory engine | RadioMind CLI/API/MCP |

This is the current first step. It is documentation/product positioning only.

**RadioHeaderMind-1b — backend contract audit**

In the RadioHeader repo, audit current storage/search/Echo flow and define:

```python
MemoryBackend.search(query, scope, project=None)
MemoryBackend.write(entry, scope, project=None)
MemoryBackend.digest(project=None)
MemoryBackend.status()
```

RadioMind becomes one backend implementation. RadioHeader keeps behavior rules.

**RadioHeaderMind-1c — setup/onboarding design**

Design `radioheader setup --with-radiomind`:

- ask whether to enable RadioMind backend;
- ask whether to import existing RadioHeader memory;
- ask before writing hooks/MCP/project files;
- use host LLM for summaries/Echo when available;
- leave managed retrieval as a future optional step.

Do not implement managed retrieval in this phase.

## 4. Power-User Path

Targets: Python users, CLI users, MCP integrators, researchers.

### 4.1 Current valid path

RadioMind should keep direct usage:

```bash
radiomind init
radiomind doctor
radiomind ingest file.jsonl
radiomind search "query"
radiomind refine
radiomind dream
radiomind train --prepare-habits
radiomind deploy
radiomind mcp-server
```

Python:

```python
import radiomind
mind = radiomind.connect(llm=host_llm)
```

### 4.2 Implementation phases

**PowerUserOnboarding-1a — command map audit**

- Confirm all documented commands exist.
- Confirm error messages map to next actions.
- Confirm `python -m radiomind` parity.
- No code changes.

**PowerUserOnboarding-1c — interactive onboarding command**

Implemented one optional command:

```bash
radiomind onboard
```

It is not mandatory. It:

- detect config;
- report available LLM/retrieval/train capabilities;
- asks before writing config;
- recommend host LLM first;
- mention managed retrieval as "future / not configured" until product exists.

## 5. Managed Retrieval: Deferred Subscription Design

Do not implement now.

When opened later, it should be a separate line:

**ManagedRetrieval-1a — privacy and product design**

Must answer:

- What text leaves the machine?
- Is raw text stored server-side?
- Are vectors cached?
- How does the user delete data?
- How are sensitive domains excluded?
- How is quota/cost shown before bulk import?
- How does the host ask for authorization?

Suggested product:

| Plan | Capability |
|---|---|
| Free local | FTS / optional local embedding |
| Own key | user-supplied embedding/rerank provider |
| Managed retrieval | RadioMind-hosted embedding + rerank, opt-in |

Never silently upload memory.

## 6. Implementation Advice For CC

### First task to give CC

Open **RadioHeaderMind-1a**.

Scope:

- Pure documentation.
- Update README / README_zh / docs/integration if needed.
- Add "Which entry should I use?" section:
  - personal agent -> RadioMind provider;
  - coding agent -> RadioHeader with RadioMind backend;
  - power user -> RadioMind CLI/API/MCP.
- Do not touch runtime.
- Do not implement subscription.
- Do not modify RadioHeader repo yet.

Acceptance:

- A new user can tell whether to install RadioHeader or RadioMind.
- Programming-agent users are no longer directed primarily to raw RadioMind.
- Existing quickstart still works for power users.

### Second task

Open **PersonalOnboarding-1a**.

Scope:

- Read existing Hermes/MCP integration.
- Identify where host LLM can be reused.
- Identify what import actions need user authorization.
- Produce a design log only.

### Third task

Open **PowerUserOnboarding-1a**.

Scope:

- Audit direct CLI/API/MCP command map against docs.
- Produce gap list.
- No code unless a command is documented but missing.

### Later task, different repo

Open **RadioHeaderMind-1b** in the RadioHeader repo.

Final target:

- Programming agents should enter through RadioHeader.
- RadioHeader should own rules, hooks, Echo, project onboarding, and behavior
  contracts.
- RadioMind should be available underneath as an optional memory/retrieval
  backend, not as a replacement for RadioHeader.
- RadioHeader must preserve native fallback behavior and explicit authorization
  boundaries before calling any RadioMind operation with cost, LLM calls, or
  mutation.

Scope:

- First do a read-only backend-contract audit in RadioHeader.
- Treat the current integration as CLI/file compatibility, not as an already
  formal backend abstraction.
- Verify current `radioheader search` -> `radiomind rh-search` and
  `radioheader consolidate` -> `radiomind rh-consolidate` delegation before
  proposing any new interface.
- Define a backend contract only if the RadioHeader repo audit proves it is
  needed.
- Do not migrate memory yet.
- Do not change RadioMind.

RadioMind-side prep is captured in
`projectBasicInfo/06_RADIOHEADER_BACKEND_PREP.md`. RadioHeader repo changes
must happen in the RadioHeader/RadioHead project, not from this repo.

## 7. Done Criteria For This Productization Track

This track is complete when:

1. Public docs route the three user types correctly.
2. Personal-agent onboarding has a host-capability and authorization design.
3. Power-user CLI/API/MCP path is documented and internally consistent.
4. RadioMind-side docs capture the RadioHeader-first final target and a scoped
   RadioHeader-side backend-contract audit task, ready to open in the
   RadioHeader repo.
5. Managed retrieval is explicitly deferred, with privacy questions captured.
