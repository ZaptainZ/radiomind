# 06 — RadioHeader Backend Prep

> Date: 2026-06-13  
> Status: RadioMind-side preparation only.  
> Scope: read-only understanding of the current RadioHeader integration surface.
> Do not modify the RadioHeader repository from this track.

## 0. Decision

RadioHeader work should happen in the RadioHeader/RadioHead project, not from
the RadioMind repo.

RadioMind should prepare by documenting the current integration shape and the
contract questions that RadioHeader must answer later. This keeps the product
route clear without making cross-repo changes from the wrong workspace.

## 0.1 Final Goal

The product goal is:

> Programming agents should enter through RadioHeader. RadioHeader should own
> the agent-facing rules, hooks, Echo workflow, and project behavior. RadioMind
> should be available underneath as an optional memory engine that can improve
> retrieval, consolidation, and long-term memory quality without taking over
> RadioHeader's rule layer.

The desired end state is not "replace RadioHeader with RadioMind." The desired
end state is:

1. RadioHeader remains the recommended entry point for programming agents.
2. RadioMind can be used by RadioHeader as a stronger memory/retrieval backend
   where it is actually useful.
3. RadioHeader keeps deterministic fallback behavior when RadioMind is absent,
   unhealthy, or not authorized.
4. RadioHeader continues to own Echo writes, hook timing, rule injection, and
   source-of-truth files unless a later RadioHeader-side audit proves that a
   specific write path should move.
5. Any RadioMind operation that calls LLMs, mutates memory, rewrites digests, or
   has non-trivial cost must remain visible to RadioHeader and subject to the
   same host/user authorization principles used for personal-agent onboarding.

This document is the RadioMind-side handoff. It records what exists today and
what RadioHeader must decide later.

## 1. What Was Read

Read-only sources:

- RadioHeader runtime data: `~/.claude/radioheader/`
- RadioHeader source checkout:
  `~/Library/Mobile Documents/com~apple~CloudDocs/DarkForce/RadioHead/radioheader/`
- RadioHeader docs:
  - `radioheader/README.md`
  - `radioheader/docs/how-it-works.md`
  - `radioheader/docs/mcp-server.md`
- RadioMind bridge code:
  - `src/radiomind/adapters/radioheader.py`
  - `src/radiomind/cli/main.py`

No files in RadioHeader were modified.

## 2. Current Integration Shape

The current integration is **CLI/file compatibility**, not a formal backend
abstraction.

RadioHeader owns:

- project behavior contracts;
- `CLAUDE.md` / `AGENTS.md` rule injection;
- hooks and Echo flow;
- topics / shortwave / project registry file layout;
- context digest lifecycle;
- native FTS5 search;
- MCP server over the RadioHeader file layer.

RadioMind currently provides:

- `migrate-radioheader`: import topics, shortwave, and registry into RadioMind;
- `rh-search`: return RadioHeader-compatible search JSON from RadioMind search;
- `rh-consolidate`: run dream/refinement and write a RadioHeader-compatible
  `context-digest.md`;
- adapter parsers for topic/shortwave/registry files.

RadioHeader detects RadioMind only by checking whether `radiomind` is on PATH.
When present:

| RadioHeader command | Native path | RadioMind path |
|---|---|---|
| `radioheader search` | `fts-search.py` | `radiomind rh-search` |
| `radioheader consolidate` | `attn-consolidate.py` | `radiomind rh-consolidate` |

If RadioMind is absent or fails, RadioHeader falls back to the native path.

## 3. Important Boundary

RadioHeader is not currently calling a `MemoryBackend` interface.

Therefore RadioMind documentation should not imply that RadioHeader already
uses RadioMind as a live backend for all reads/writes. The accurate current
phrasing is:

> RadioHeader can auto-upgrade selected commands when RadioMind is installed:
> search delegates to `radiomind rh-search`, and consolidate delegates to
> `radiomind rh-consolidate`. RadioHeader still owns capture, rules, hooks,
> Echo, and its file-based experience layer.

Future backend contract work belongs in the RadioHeader repo.

## 4. Current RadioMind Adapter Surface

`RadioHeaderAdapter` currently supports three roles:

| Role | Method / command | Side effect |
|---|---|---|
| migration | `migrate()` / `radiomind migrate-radioheader` | writes RadioMind store |
| search bridge | `search()` / `radiomind rh-search` | read-only |
| consolidate bridge | `consolidate()` / `radiomind rh-consolidate` | writes RadioHeader `context-digest.md`; may run dream/refinement |

This is enough for current compatibility, but not enough to claim a general
backend contract.

## 5. Fit / Non-Fit Split

RadioMind is a good fit for:

- semantic/pyramid search over imported RadioHeader data;
- habit/refinement/dream over experience entries;
- generating richer context digest;
- long-term future managed retrieval, if privacy/product design is done.

RadioHeader should continue owning:

- behavioral rules (`Search -> Apply -> Trace`);
- project onboarding and templates;
- Echo rules and log obligations;
- hook lifecycle;
- shortwave quality standards;
- community sharing semantics;
- project registry source-of-truth unless explicitly migrated.

## 6. Later RadioHeader-Side Questions

When work moves to the RadioHeader repo, answer these there:

1. Should RadioHeader remain file-first with optional RadioMind command
   delegation?
2. Or should it gain a formal backend abstraction?
3. If formal backend:
   - Which operations need backend support?
   - Which stay file-native?
   - How are hooks kept deterministic and cheap?
   - How is fallback to native FTS preserved?
4. How should RadioHeader expose authorization / side-effect boundaries if
   RadioMind operations call LLMs or mutate memory?

## 6.1 RadioHeader-Side TODO

Do this later in the RadioHeader/RadioHead project:

- [ ] Verify current delegation behavior from the RadioHeader CLI:
  - `radioheader search` -> `radiomind rh-search`
  - `radioheader consolidate` -> `radiomind rh-consolidate`
  - native fallback when RadioMind is absent or fails
- [ ] Decide whether the current command delegation is enough for the product
  goal, or whether a formal backend abstraction is necessary.
- [ ] If a backend abstraction is necessary, keep v1 read-oriented and small:
  search, health, context digest, and consolidate/dry-run are plausible first
  candidates.
- [ ] Preserve RadioHeader's native FTS fallback and cheap deterministic
  startup path.
- [ ] Keep Echo writes file-native unless there is a concrete product reason to
  move them.
- [ ] Define how RadioHeader asks for authorization before invoking any
  RadioMind-backed operation with cost, LLM calls, or mutation.
- [ ] Update RadioHeader docs after the contract decision so programming-agent
  users see a clear "RadioHeader first, RadioMind optional backend" story.

Do not execute this TODO from the RadioMind repo.

## 7. Proposed Future RadioHeader Task

Open in the RadioHeader/RadioHead project, not here:

**RadioHeaderMind-1b — backend contract audit**

Scope:

- read current `radioheader` shell CLI, hooks, MCP server, docs, and templates;
- verify the current `radiomind rh-search` / `rh-consolidate` delegation path;
- decide whether a formal backend abstraction is justified;
- if yes, design the smallest interface;
- do not migrate memory;
- do not remove native FTS fallback.

Potential interface, only if justified:

```python
class ExperienceBackend:
    def search(query, *, field=None, limit=20) -> SearchResult: ...
    def context_digest(max_chars=4000) -> Digest: ...
    def consolidate(dry_run=False) -> ConsolidateResult: ...
    def health() -> BackendHealth: ...
```

Do not include write paths in the first backend interface unless there is a
clear product reason. RadioHeader's Echo write path is behavior-critical and
should stay file-native until proven otherwise.

## 8. RadioMind-Side Preparation

RadioMind should keep these compatibility surfaces stable:

- `radiomind rh-search <query> [--limit N]`
- `radiomind rh-consolidate [--dry-run]`
- `radiomind migrate-radioheader [--path PATH]`
- `RadioHeaderAdapter.parse_*` behavior for current topic/shortwave formats

If these change, document the compatibility impact in both projects.

RadioMind-side work for this stage is complete when:

- the current bridge is documented honestly as CLI/file compatibility;
- the future goal is written as a RadioHeader-side TODO instead of being
  implied as already implemented;
- RadioMind does not change RadioHeader files from this repo;
- `migrate-radioheader`, `rh-search`, `rh-consolidate`, and
  `RadioHeaderAdapter` remain the stable compatibility surface until the
  RadioHeader-side audit says otherwise.

## 9. Stop Point

This prep track is complete when:

1. RadioMind docs stop implying a full RadioHeader backend already exists.
2. The current CLI/file bridge is documented accurately.
3. The final "RadioHeader first, RadioMind optional backend" target is captured
   as a RadioHeader-side TODO.
4. No RadioHeader files were modified from the RadioMind workspace.
