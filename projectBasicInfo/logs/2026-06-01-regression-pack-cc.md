# Regression Pack — deterministic local smoke standard

**Date**: 2026-06-01
**Author**: Claude Code
**Status**: Done. One-command, fast, deterministic gate over the closure /
hint / SelfAnchor / JAB / closure_view surface. No ingest, no LLM, no
benchmark. Also fills the one real coverage gap: `diagnose_qid`'s
`closure_view` now has committed tests.

---

## Why (priority #3 after Diagnostic UX close-out)
The 8 behaviour categories the user listed (role/TESG suppressors, age/cashback
committers, savings/person_age hints, SelfAnchor scans, JAB/negatives) ALREADY
have unit tests. The need was a single **runnable standard** ("run this on
every architecture change") — not re-ingesting 10-15 qids (slow, stochastic,
needs LLM). So the pack is a thin orchestrator over the existing faithful-data
unit tests, by category.

## Delivered
1. `tests/test_closure_view.py` (NEW, 4 tests) — the only real gap. Loads
   `bench/end_to_end/diagnose_qid.py` and pins `_probe_closure_view` on
   faithful synthetic data: cashback committer view (value 0.75, commit
   what-if, never-overwrite-concrete), age committer view (value 7, **dual
   `sources`**, recompute_ok, confidence), committer-absent-when-no-proof,
   suppressor what-ifs (role/TESG bypass abstain, don't fire on cashback).
   Converts the ad-hoc 2b/2c smokes into committed regression tests.
2. `bench/end_to_end/regression_pack.py` (NEW) — runs a category→test-file
   manifest via pytest subprocesses, prints a per-category PASS/FAIL summary,
   exits 0 iff all pass. Run:
   `~/.radiomind-bench-venv/bin/python bench/end_to_end/regression_pack.py`
   `--integration` is accepted as a reserved slow-layer flag; no ingest/LLM
   checks are wired yet, so it prints a notice and still runs the deterministic
   fast pack only.

## Manifest (category → tests)
| category | tests |
|---|---|
| committer:cashback | test_cashback_commit_closure / _field_9aaed6a3 / _proof_result_cashback_adapter |
| committer:age | test_age_interval_commit / _proof_result_age_adapter |
| committer:shared-gate | test_commit_on_abstain |
| suppressor:role | test_role_mismatch_guard |
| suppressor:temporal-endpoint | test_temporal_endpoint_guard |
| hint:savings | test_savings_arithmetic_hint |
| hint:person-age | test_typed_event_hint |
| hint:arithmetic-core | test_arithmetic_hint |
| self-anchor | test_self_anchor |
| jab:abstain-veto | test_jab1_abstain_veto |
| diagnostic:closure-view | test_closure_view |

## Result
**ALL 11 categories PASS — ~294 tests in ~1.2s, exit 0** (local
`~/.radiomind-bench-venv` py3.13). Every category is green in the
dependency-light bench venv (the curated subset avoids the optional-dep
modules — onnxruntime / sentence_transformers / mlx — that make the full
`tests/` run noisy there).

## How to extend
Add a behaviour to the gate = add its test file under the right category in
`PACK`. The pack stays the single source of truth for "what must stay green
on every architecture change."

## Files
- `tests/test_closure_view.py` (new)
- `bench/end_to_end/regression_pack.py` (new)
