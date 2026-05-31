# Phase2-1c — ProofResult carrier for age_interval (telemetry-only)

**Date**: 2026-05-31
**Author**: Claude Code
**Status**: Done. age_interval now produces a `ProofResult` via an adapter,
and the closure renders **from** it (single source of truth for the
committed bytes). **No gate / trigger / output byte changed.** This is the
real stress test for `sources: list[Source]` (dual provenance) — it passed.
Both committers (cashback, age) now carry `ProofResult` losslessly.
role / TESG / runner untouched; no dispatcher, no registry.

---

## Why age is the stress test
cashback (1b) had a single rate source. age has **dual provenance**:
- `at_age` — quote only, **no turn_id** (`_find_age_at_event` returns
  `(past_age, past_evidence)`; the strict regex yields no id).
- `current_age` — quote, plus a **turn_id only on the SelfAnchor store-scan
  path** (retrieve path has no id).
This is exactly why `ProofResult.sources` is a **list of `Source(role,
turn_id, quote)`** rather than flat `source_turn_id`/`quote` — neither
closure could be expressed with flat fields (age dual, cashback split).

## Changes
- `src/radiomind/core/age_interval_commit.py`:
  - Added `age_interval_proof_to_result(*, skill_value, unit, mode,
    past_age, current_age, past_evidence, current_evidence,
    current_scan_scope, confidence) -> ProofResult`. It owns the rendering
    (the verbose "Verified: …" string moved verbatim) so the committed bytes
    live in exactly one place.
  - `maybe_age_interval_commit_closure` now ends with
    `return age_interval_proof_to_result(...).rendered` — the gates and
    proof extraction above are **unchanged**.
- `tests/test_proof_result_age_adapter.py` (new, 4 tests):
  - live closure output == adapter `.rendered` (byte-identity) + the
    existing exact-output substrings.
  - dual `sources` (at_age: turn_id None, quote; current_age: turn_id None
    on retrieve, quote), value, inputs, subject None, confidence carried.
  - store-scan path: `sources[1].turn_id` + `scan_scope` carried, and the
    "SelfAnchor store-scan: turn …" suffix appears in `rendered`.
  - `recompute_ok` reflects the older/younger arithmetic (True/False).

### Field mapping (age proof → ProofResult)
| age proof piece | ProofResult |
|---|---|
| `skill_value` (=recomputed) | `value` |
| `past_age`, `current_age`, `mode` | `inputs` |
| `past_evidence` | `sources[0]` (role="at_age", turn_id=None) |
| `current_evidence` (+ store-scan turn_id) | `sources[1]` (role="current_age") |
| `current_scan_scope[1]` | `scan_scope` |
| `conf` | `confidence` |
| (no merchant-like anchor) | `subject = None` |
| recompute == skill_value | `recompute_ok` |

## Verification
- `tests/test_age_interval_commit.py` (age gates + exact output) +
  `test_proof_result_age_adapter.py` + the three cashback files →
  **61 passed** (local venv py3.13). The pre-existing age tests passing is
  the proof the adapter refactor is byte/gate-identical.
- `age_interval_commit.py` syntax-clean.
- No change to role_mismatch_guard / temporal_endpoint_guard / arithmetic_hint's
  cashback gate / run_longmemeval_mem0.py.

## Status of the carrier after 1c
`ProofResult` now losslessly holds BOTH committer proofs:
- cashback: 1 source (rate), `subject`=merchant, `confidence`=None.
- age: 2 sources (at_age + current_age), `subject`=None, `confidence`=conf.
Every field has been exercised by at least one closure; `sources` list,
`subject`, `confidence`, `scan_scope` all justified by real data.

## Next (Phase2-1d, only if warranted)
Both committers carry `ProofResult` as telemetry without behavior change.
A shared `commit_on_abstain(proof, llm_answer)` could now consume the
carrier (gate on `_is_pure_abstain` + `recompute_ok`, render `proof.rendered`)
and replace the two closures' tails — but only if it stays byte-identical and
each migration is test-guarded. The suppressor family (role, TESG) stays
out of the proof registry entirely (different abstraction — no value, no
recompute, inverted abstain polarity; see 1a §3). No dispatcher.
