# Repo Hygiene — Bench Artifacts and Checkpoints

**Date**: 2026-05-31
**Author**: Codex
**Status**: Complete. Cleaned regenerable bench noise while preserving
result `.json` artifacts for explicit future review.

---

## Problem

`git status` was dominated by bench artifacts:

- 86 untracked files before cleanup.
- 27 iCloud conflict copies under `bench/end_to_end/validation/` with
  names like `... 2.json` / `...checkpoint 2.jsonl`.
- 32 tracked checkpoint files under `bench/end_to_end/validation/`.
- Many untracked checkpoint files from smoke / validation runs.
- `.codex/config.toml` was local config but not ignored.

The project history intentionally commits selected milestone `.json`
results, so ignoring all bench `.json` would be too blunt.

## Policy

- Result `.json` files are **not** ignored. Keep them visible until a human
  decides whether they are milestone artifacts or disposable smoke output.
- Checkpoint `.jsonl` files are regenerable/resumable intermediates and are
  ignored.
- `.codex/` is local agent config and is ignored.
- iCloud conflict copies with `" 2"` suffix are deleted only when the
  canonical file exists.

## Actions

1. Deleted 27 iCloud conflict copies with canonical counterparts.
2. Removed 32 tracked checkpoint files from the git index with
   `git rm --cached`; local disk copies remain and are now ignored.
3. Deleted 55 untracked checkpoint files from disk.
4. Added `.gitignore` rules:

```gitignore
# Bench artifacts — resumable checkpoints are regenerable.
bench/end_to_end/**/*.checkpoint.jsonl

# Local agent config.
.codex/
```
5. Synced the policy to `projectBasicInfo/01_PROJECT_OVERVIEW.md` and
   project memory (`project_bench_artifact_hygiene.md`).

## Verification

After cleanup:

- `find bench/end_to_end -name '* 2.*'` → 0.
- `git ls-files -- 'bench/end_to_end/**/*.checkpoint.jsonl'` → 0.
- `.codex/config.toml` is ignored.
- Checkpoint paths are ignored by `.gitignore`.
- Result `.json` files remain untracked and visible for explicit review.

## Follow-up

If a future bench result is a milestone, add the `.json` explicitly. Do not
commit checkpoint files unless there is a specific debugging need and the
log explains why.
