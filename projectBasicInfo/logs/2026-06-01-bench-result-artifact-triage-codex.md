# Bench Result Artifact Triage

**Date**: 2026-06-01
**Author**: Codex
**Status**: Complete. Removed disposable untracked smoke result JSON files and
left the five full LoCoMo n=100 artifacts for explicit user decision.

---

## Context

After the 2026-05-31 repo hygiene pass, checkpoints and local agent config were
ignored, but 24 untracked result `.json` files intentionally remained visible.
The policy is to avoid blanket-ignoring result JSON because selected milestone
bench outputs are part of the project history.

## Triage Result

The 24 untracked result files split into:

- 5 full LoCoMo n=100 runs with possible archival value.
- 19 small/ad-hoc smoke outputs superseded by later submitted artifacts.

## Actions

Deleted the 19 low-value smoke outputs:

- `bench/end_to_end/tc1b-run{1,2,3,4,5}.json`
- `bench/end_to_end/validation/v6.1-gap-d-smoke4-rerun.json`
- `bench/end_to_end/validation/v6.1-gap-d-smoke4.json`
- `bench/end_to_end/validation/v6.1.1-smoke4-run{1,2}.json`
- `bench/end_to_end/validation/v6.2-gap-c-smoke6.json`
- `bench/end_to_end/validation/v6.2.1-gap-c-smoke6.json`
- `bench/end_to_end/validation/v6.2.2-gap-c-smoke6.json`
- `bench/end_to_end/validation/v6.3-lme-smoke4.json`
- `bench/end_to_end/validation/v6.4-lme-smoke4.json`
- `bench/end_to_end/validation/v6.4a-lme-smoke4.json`
- `bench/end_to_end/validation/v6.5-lme-smoke4.json`
- `bench/end_to_end/validation/v6.5.{1,3,4}-flip10-smoke.json`

No tracked files were deleted in this step.

## Preserved for Decision

The remaining untracked result JSON files are full LoCoMo n=100 runs:

| file | n | acc |
|---|---:|---:|
| `bench/end_to_end/locomo-V6.1.1-deepseek-judge4o.json` | 100 | 0.87 |
| `bench/end_to_end/validation/v6.3-locomo-smoke.json` | 100 | 0.90 |
| `bench/end_to_end/validation/v6.4-locomo.json` | 100 | 0.84 |
| `bench/end_to_end/validation/v6.4a-locomo.json` | 100 | 0.88 |
| `bench/end_to_end/validation/v6.5-locomo.json` | 100 | 0.90 |

These may be committed as historical V6 LoCoMo progression artifacts, or
deleted if the already-tracked final LoCoMo milestone is considered sufficient.

## Verification

`git status --short` now shows only the five preserved LoCoMo n=100 result
files as untracked bench artifacts.

## Follow-up

Decide whether to archive the five LoCoMo n=100 files in git or delete them.
Until then, leaving them untracked is intentional and keeps the decision
visible.
