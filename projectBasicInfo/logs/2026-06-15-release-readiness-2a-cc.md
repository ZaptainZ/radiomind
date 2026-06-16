# ReleaseReadiness-2a — pre-release all-entry smoke + doc-parity audit

**Date:** 2026-06-15
**Author:** Claude Code (cc)
**Scope:** Smoke / audit / doc-consistency only. No benchmark, no managed
retrieval, no subscription, no reranker research, no auto model install, no data
upload. Fix small doc breakpoints only; stop & report on any runtime breakpoint.

**Goal:** confirm RadioMind's entry points are *really* usable for all three
audiences (personal-agent/provider, power-user CLI/Python/MCP, coding-agent via
RadioHeader) — "not just unit tests green, user entries green."

## Method

Fresh **py3.12** venv `/tmp/rm-rr2a-venv`, bare `pip install -e .` (no extras), so
this is a true clean install (bench venv py3.13 has broken pyexpat). Embedding-tier
wording re-checked on the existing py3.12 `[embedding]` venv (no new download).

## Results

| # | Entry / command | Result | Finding |
|---|---|---|---|
| A | `pip install -e .` (bare) → import | PASS | version 0.1.0 |
| A | `radiomind --help` / `python -m radiomind --help` | PASS | both work; console script on PATH |
| A | `init → learn → search → status` | PASS | learn=1; `search "running"` → `[fact/?] … method=fts` (expected bare-install) |
| B | onboard / doctor / status (bare) | PASS | tier = `FTS-only (+ typed-facet fallback)`; recommends `[embedding]`; offers `[rerank]` |
| B | embedding-installed venv | PASS | tier = `local embedding`; embedding nudge replaced by "best local retrieval active" |
| B | remote key, no consent | PASS | "remote retrieval available but disabled until consent" (status + doctor) |
| B | remote key + consent | PASS | tier `remote (consented)`; "memory/query/candidate text is sent to a third-party API" |
| B | managed retrieval | PASS | `future / not configured` (PARK, not misleading) |
| C | `train` (no opt-in) | PASS | refuses: "LoRA is supported but opt-in… export RADIOMIND_ENABLE_LORA=1" |
| C | `train --data-only` (opt-in, small store) | PASS | shows thresholds (habits 0/5, domains 0/2, examples 0/30) + next step; no training; flags DATA-VOLUME not LLM failure |
| D | `RadioMindProvider().readiness()` (no authz) | PASS | `privacy_status=local_only`; `background_hooks=unsupported`; `recommended_next_action` = wire host LLM |
| D | provider background side-effects | PASS | ingest/refine/dream each gated on scopes (`ingest_new_turns`/`background_refinement`/`dream_after_session`), no-op without grant; `auto_dream=False` default |
| E | doc CLI commands vs actual | PASS | all valid (`deploy`,`train` exist; "import" was a Python-import false positive) |
| E | MCP tool count | **FIXED** | code = 17; README L331 & README_zh L321 said "9 tools" (stale) → corrected to 17; api-reference already lists 17; README L448 already 17 |
| E | Hermes tool count | PASS | integration.md "4 tools" matches code (search/learn/habits/status) |
| E | onboard text vs docs | PASS | 3-audience routing identical in onboard and README |
| F | RadioHeader-first recommendation | PASS | README + onboard both route coding agents to RadioHeader first; no Header repo touched |

## Breakpoints found & fixed (docs only)

- **README.md** L331 `MCP (9 tools)` → `MCP (17 tools)`.
- **README_zh.md** L321 `MCP（9 工具）` → `MCP（17 工具）`.

Root cause: the tool surface grew to 17 (PowerUserOnboarding-1a updated some doc
sites to 17 but these two Claude-Code rows were missed). No other stale counts
remain (`grep` sweep clean). **No runtime breakpoints found** — runtime untouched.

## Conclusion

**PASS.** All three user entries are green on a clean install: minimal CLI path,
the retrieval-tier ladder (bare → embedding → reranker → remote-consent → managed-
PARK) reads correctly at every state, LoRA is opt-in with actionable thresholds,
the provider is local-only/deny-by-default with a readiness next-step, and docs/CLI
are consistent (two stale tool-counts fixed). RadioMind can be stated as
deliverable on user-path grounds, not just test-suite grounds.

See [[project_retrieval_ux]], [[project_managed_retrieval]],
[[project_release_candidate_1a]] (the earlier clean-install RC), [[project_cli_product_ux]].
