# ReleaseCandidate-1a — Clean-install release smoke

**Date:** 2026-06-13
**Author:** Claude Code (cc)
**Scope:** Confirm "this repo is already deliverable to a real user." Not a feature task.
Only fix install / docs / entry-point breakpoints; do not touch architecture.

## Goal

Prove the user path works from a **clean install** — not from the dev tree, not
from "tests pass." Verify CLI entry points, the minimal `init → learn → search →
status → onboard` path, and that the commands printed in README / quickstart
actually run.

**完成标准:** clean install 下用户路径没有文档/命令断点。

## Approach

1. Clean venv `/tmp/rm-rc-venv` on **python3.12** (3.13_1/3.14 ship broken
   `pyexpat` — symbol mismatch with system libexpat; this is a recurring trap).
   `pip install -e .` → succeeds.
2. Entry points: `radiomind --help`, `python -m radiomind --help`,
   `import radiomind` (version 0.1.0) — all OK.
3. Minimal path with sandbox `RADIOMIND_HOME=/tmp/rm-rc-*`:
   `init → onboard → learn → learn → search → status → doctor` — all OK.
4. **Ran every Python/CLI snippet from README, README_zh, quickstart verbatim
   on the clean venv.**

## Findings — real doc breakpoints (fixed)

The runtime was healthy. The breakpoints were all in **documentation examples
that don't survive the L1 gate or the no-embedder default**:

1. **README / README_zh headline** used
   `"I run every morning and sleep much better since"` /
   the search term `"health habits"` (en) — the English sentence is **DROPPED by
   the L1 regex-whitelist gate** (no whitelist verb), so `add` returns `added=0`
   and `search` returns `[]`. The very first code a user copies returned nothing.
   - Fix: `"I like running every morning"` (passes gate via the preference
     pattern) + `search("running")` (FTS keyword overlap — works with **no
     embedder**) + an explicit `pip install 'radiomind[embedding]'` note for
     semantic recall. Corrected the `digest()` comment from a fabricated
     `"User: likes running every morning"` to the truthful "compact context for
     your system prompt" (a one-fact no-LLM store digests to
     `Memory: 1 entries ... / Model: qwen3:0.6b`).
   - zh headline: `我每天跑步…` passes the (richer) CJK gate, but `search("健康习惯")`
     shares no characters with the stored text → no FTS hit without an embedder.
     Changed to `search("跑步")` + the same embedding note.

2. **quickstart Step 3** showed `search("exercise")` → claimed output
   `[fact/health] I like running every morning`. Two errors: (a) `exercise` only
   matches `running` semantically → needs the embedding extra bare `pip install`
   lacks; (b) the domain is **not** `health` (the classifier has no `running`
   keyword) — it renders `[fact/?]`. Changed to `search("running")`, relaxed the
   shown domain tag, and added the embedding note. Same fix on the CLI
   `radiomind search "exercise"` line.

**Root cause, one sentence:** doc examples were written against an idealized
extractor/embedder, not against the conservative defaults a clean
`pip install radiomind` actually ships (regex gate + FTS-only search).

## Verification

- Corrected en + zh headline snippets re-run on clean venv:
  `add added=3 skipped=1` / `search('running')` finds the fact; zh `add added=1`,
  `search('跑步')` finds it.
- Documented CLI chain on a fresh `RADIOMIND_HOME`:
  `init → learn → search (method=fts) → status → onboard` all succeed.
- No test references README/quickstart text; docs-only edits, suite unaffected.

## Files changed

- `README.md` — headline example (add/search/digest) + embedding note
- `README_zh.md` — headline example + embedding note
- `docs/quickstart.md` — Step 3 search + CLI search line + embedding note

## Conclusion

**PASS.** Clean-install user path has no doc/command breakpoints. Architecture
untouched. Per the plan, leaving the RadioMind repo next for RadioHeaderMind-1c
(RadioHeader repo). Managed retrieval / vector subscription still deferred.
