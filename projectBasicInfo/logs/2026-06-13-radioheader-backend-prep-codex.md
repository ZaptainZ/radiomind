# RadioHeader Backend Prep — RadioMind-Side Notes

**Date**: 2026-06-13  
**Author**: Codex  
**Status**: Complete. RadioMind-side documentation only. No RadioHeader files changed.

## Background

After the three-entry onboarding route was documented, the user clarified the
next boundary:

- understand the RadioHeader side first;
- prepare RadioMind for that integration;
- do not modify RadioHeader from this repo;
- actual RadioHeader work should happen later inside the RadioHeader project.

## Work Done

Read-only inspection:

- `~/.claude/radioheader/` runtime data and registry;
- `/Users/zaptain/Library/Mobile Documents/com~apple~CloudDocs/DarkForce/RadioHead/radioheader/`;
- RadioHeader README / how-it-works / MCP docs;
- RadioHeader CLI delegation logic;
- RadioMind `RadioHeaderAdapter` and CLI commands.

Documentation added:

- `projectBasicInfo/06_RADIOHEADER_BACKEND_PREP.md`

Documentation updated:

- `projectBasicInfo/04_PRODUCT_ONBOARDING_IMPLEMENTATION.md`
- `projectBasicInfo/01_PROJECT_OVERVIEW.md`

## Key Finding

Current integration is **CLI/file compatibility**, not a formal backend
abstraction.

RadioHeader:

- owns rules, hooks, Echo, topics, shortwave, registry, native FTS, and context
  digest lifecycle;
- detects `radiomind` on PATH;
- delegates `radioheader search` to `radiomind rh-search` when available;
- delegates `radioheader consolidate` to `radiomind rh-consolidate` when
  available;
- falls back to native scripts when RadioMind is absent or fails.

RadioMind:

- can import existing RadioHeader data via `migrate-radioheader`;
- can serve compatible search JSON via `rh-search`;
- can run dream/refinement + write a compatible digest via `rh-consolidate`.

## Decision

Do not claim RadioHeader already has a formal RadioMind backend.

Accurate wording:

> RadioHeader can auto-upgrade selected commands when RadioMind is installed.
> Search delegates to `radiomind rh-search`; consolidate delegates to
> `radiomind rh-consolidate`. RadioHeader still owns capture, rules, hooks,
> Echo, and the file-based experience layer.

## Final Goal Captured As TODO

The desired product end state is now explicit:

- programming agents enter through RadioHeader;
- RadioHeader keeps owning rules, hooks, Echo, project onboarding, and behavior
  contracts;
- RadioMind becomes an optional memory/retrieval backend under RadioHeader where
  useful;
- RadioHeader keeps native fallback behavior;
- RadioHeader must gate any RadioMind-backed cost, LLM call, or mutation through
  host/user authorization.

This is a future RadioHeader-side task, not an implementation already completed
in RadioMind.

## Future RadioHeader Task

Open later in the RadioHeader/RadioHead project:

**RadioHeaderMind-1b — backend contract audit**

Scope:

- verify current CLI delegation behavior;
- decide if a formal backend abstraction is justified;
- if yes, design the smallest read-oriented interface;
- keep native FTS fallback;
- do not migrate Echo writes away from files unless there is a clear product
  reason.

The RadioMind side is complete for now: it documents the current bridge,
records the final target, and preserves `migrate-radioheader` / `rh-search` /
`rh-consolidate` compatibility until the RadioHeader audit says otherwise.

## Verification

No runtime was changed. No benchmark was run. RadioHeader files were only read.

`git diff --check` should be sufficient for this documentation-only change.
