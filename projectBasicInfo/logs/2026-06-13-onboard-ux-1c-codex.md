# OnboardUX-1c — `radiomind onboard` 首跑引导

**Date**: 2026-06-13  
**Author**: Codex  
**Status**: Complete. Runtime + docs, no benchmark.

## Background

After the three-entry onboarding work, RadioMind still had one local
power-user UX gap: the docs mentioned `radiomind onboard` as a future optional
command, but the command did not exist. Users could run `init`, `doctor`, and
`status`, but there was no single first-run command that explained which route
to use, whether config existed, which LLM path was visible, or why managed
retrieval was not configured.

This is RadioMind-side work only. It does not modify RadioHeader and does not
start managed retrieval / subscription design.

## Goal

Add an optional first-run guide:

- read-only by default;
- no LLM calls;
- no train / ingest / benchmark;
- no config writes unless explicitly requested;
- recommend host LLM first;
- keep managed retrieval marked as future / not configured.

## Implementation

Changed `src/radiomind/cli/main.py`:

- added `radiomind onboard`;
- added `radiomind onboard --print-config-template`;
- added `radiomind onboard --write-config-template`;
- writes ask for confirmation unless `--yes` is passed;
- existing config is protected unless `--force` is passed;
- `radiomind init` now prints `Next: run radiomind onboard`.

The default report shows:

- three entry routes:
  - coding agents -> RadioHeader first;
  - personal agents -> RadioMind provider;
  - power users -> CLI / Python / MCP;
- home/config/db/memory count;
- API-key env vars visible to auto-detect;
- configured LLM profiles;
- RadioHeader presence;
- LoRA opt-in status;
- managed retrieval status (`future / not configured`);
- next commands.

The generated config template is intentionally explicit and commented. Most
users still do not need it because host LLM, env vars, and local Ollama are
auto-detected first.

## Documentation

Updated:

- `README.md`
- `README_zh.md`
- `docs/quickstart.md`
- `docs/api-reference.md`
- `projectBasicInfo/04_PRODUCT_ONBOARDING_IMPLEMENTATION.md`
- `projectBasicInfo/01_PROJECT_OVERVIEW.md`

## Verification

- `tests/test_cli_product_ux.py`: 16 passed
  - default onboard report is read-only;
  - template is valid TOML;
  - write path works with `--yes`;
  - overwrite is refused without `--force`;
  - report recommends host LLM before config.

## Boundaries

Did not:

- touch RadioHeader;
- implement managed retrieval / subscription;
- ask users for generic LLM keys by default;
- change `init` semantics beyond printing the next step;
- run benchmark.

## Conclusion

RadioMind now has a concrete first-run command for direct users. This closes
the remaining RadioMind-side power-user onboarding gap that had been left as
NICE_TO_HAVE after PowerUserOnboarding-1b.
