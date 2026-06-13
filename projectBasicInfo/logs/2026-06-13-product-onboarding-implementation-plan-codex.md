# Product Onboarding Implementation Plan

**Date**: 2026-06-13  
**Author**: Codex  
**Status**: Completed. Documentation/planning only; no runtime changes.

## Background

The prior productization work made RadioMind usable from multiple surfaces:

- personal-agent memory provider paths;
- CLI / Python / MCP hard-core usage;
- LoRA train/deploy/fuel flow;
- installation and quickstart documentation.

The open product question was not another low-level feature. It was entry-point
design: ordinary users should not have to understand all RadioMind internals,
and coding-agent users should not be routed directly to raw RadioMind when
RadioHeader is the correct behavior layer.

The user also clarified two subscription constraints:

1. Do not offer a generic LLM subscription for now; prefer host-agent LLM
   capability.
2. Managed vector/retrieval subscription is plausible but should be deferred
   until the rest of onboarding is shaped.

## Decision

Created an implementation plan with three user-facing routes:

| User type | Entry |
|---|---|
| Personal agent users: Hermes / OpenClaw / future RadioHand | RadioMind memory provider |
| Programming-agent users: Codex / Claude Code / Cursor | RadioHeader, with RadioMind as backend |
| Power users: Python / CLI / MCP | RadioMind native API |

The plan explicitly states:

- host LLM first;
- no generic RadioMind LLM subscription in v1;
- managed embedding/rerank subscription deferred;
- all side effects require host-mediated user authorization;
- programming-agent users should be told to use RadioHeader first.

## Files

- `projectBasicInfo/04_PRODUCT_ONBOARDING_IMPLEMENTATION.md`
  - New implementation plan.
  - Defines personal-agent, RadioHeader, and power-user product paths.
  - Captures subscription and authorization boundaries.
  - Includes concrete CC implementation order.
- `projectBasicInfo/01_PROJECT_OVERVIEW.md`
  - Added pointer to the new implementation plan and summarized the product
    route decision.

## Implementation Advice Captured

Recommended sequence for CC:

1. **RadioHeaderMind-1a** — doc-only positioning:
   - public docs should route coding-agent users to RadioHeader;
   - no runtime changes.
2. **PersonalOnboarding-1a** — read-only audit:
   - inspect Hermes/MCP integration;
   - identify host LLM reuse and authorization points.
3. **PowerUserOnboarding-1a** — command map audit:
   - verify direct CLI/Python/MCP path consistency.
4. Later in the RadioHeader repo:
   - define the RadioHeader memory backend contract backed by RadioMind.

Managed retrieval is explicitly left for a later privacy/product design line.

## Validation

No tests were required: this was documentation/planning only.

Manual sanity:

- the new doc does not change README/quickstart claims;
- the overview now points to the new plan;
- no runtime source files were changed.

## Conclusion

The productization direction is now explicit:

RadioMind is the memory engine; RadioHeader is the coding-agent behavior layer;
personal agents can use RadioMind directly; hard-core users keep the native
CLI/Python/MCP path. The next actionable step is RadioHeaderMind-1a, a
doc-only public routing update.

