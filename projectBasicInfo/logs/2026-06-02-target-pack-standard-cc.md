# Contemporary target-pack standard (v1 harness)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Harness + manifest + deterministic parse tests done. The REAL
e2e run is NOT executed here (heavy ingest+LLM+judge — authorized/manual,
after key-path changes only). Distinct from `regression_pack.py` (fast,
deterministic, no LLM).

---

## Purpose
Component count is growing; pure unit tests can't catch LLM trust/retrieval
jitter in the live ingest path. The target-pack runs a curated set of
representative qids through the FULL runner (ingest + answer-LLM + judge) to
confirm the helpers/closures/skills still behave end-to-end.

## Manifest (`bench/end_to_end/target_pack.py`, qid set per user)
**required (gates exit code):**
- `031748ae_abs` — role suppressor
- `gpt4_93159ced_abs` — TESG suppressor (should abstain)
- `gpt4_93159ced` — TESG negative anchor (should keep concrete)
- `9aaed6a3` — cashback committer
- `bb7c3b45` — savings hint
- `gpt4_d12ceb0e` — person_age hint
- `c18a7dc8` — age_interval committer
- `d851d5ba` — NAR charity sum

**observe_only (reported, never reds the pack):**
- `gpt4_7abb270c` — OrderedEventList (mechanics ok, precision parked)
- `b46e15ed` — event_cluster_interval (deferred)

Deliberately excluded (signal pollution): `d6233ab6` (subjective preference),
`gpt4_194be4b3` / `gpt4_ab202e7f` (open-vocab entity norm), other out-of-scope
fails.

## Harness
- `summarize(per_query, manifest)` — pure: classifies each qid; `mode`
  separates `required` (gates `required_all_pass` / exit code) from
  `observe_only` (parked/deferred — reported, never fails). A missing required
  qid counts as fail; a missing observe is just noted.
- `main()` runs `run_longmemeval_mem0.py --qids <manifest> --sandbox
  /tmp/rm-sandbox-target-pack` with answer=deepseek-v3.2/dashscope,
  judge=gpt-4o/openrouter, then summarizes. `--report <json>` re-summarizes an
  existing result without running.
- Exit 0 iff all `required` pass; `observe_only` never reds it.

## Verification (deterministic, no runner/LLM)
- `tests/test_target_pack.py` (4): all-required-pass + observe-fail stays green;
  a failing required reds the gate; a missing required = fail; manifest shape
  (parked lines are observe_only).
- `--report` CLI smoke on a synthetic json prints the grouped required/observe
  summary correctly.
- Added to the regression pack as `harness:target-pack` (the parse logic only —
  NOT the e2e run). Full pack: **14 categories ALL PASS**.

## Boundary (per agreement)
The **full e2e target-pack run** is heavy (~50-session ingest + LLM + judge per
qid → run-time in hours) and is **manual / authorized, after key-path changes
only**. It does NOT enter the default `regression_pack.py`. Only the harness's
deterministic parse logic is in the regression pack.

## Next (authorized)
Run `target_pack.py` once to establish the baseline (which required qids pass
today under the live pipeline), then treat it as the post-key-path-change gate.
Gated on explicit go. role/TESG required qids may need their gold expectations
double-checked on the first real run (the suppressor pair `gpt4_93159ced` /
`_abs` especially).

## Files
- `bench/end_to_end/target_pack.py` (new)
- `tests/test_target_pack.py` (new)
- `bench/end_to_end/regression_pack.py` (+`harness:target-pack` category)
