# Phase2-1b — ProofResult Carrier for Cashback (Telemetry-Only)

**Date**: 2026-05-31
**Author**: Codex
**Status**: Complete. Narrow carrier pilot for the COMMIT_ON_ABSTAIN
family. No runtime behavior change.

---

## Goal

Phase2-1a established that the shipped post-LLM closures are two
different families:

- **Suppressors**: role / temporal endpoint; concrete over-commit ->
  abstain.
- **Committers**: age / cashback; pure abstain -> deterministic value.

Phase2-1b only touches the committer family and only adapts cashback as a
telemetry-only pilot. Role, TESG, age, runner wiring, and commit gates are
unchanged.

## Changes

### `src/radiomind/core/proof_result.py`

New domain-agnostic frozen dataclasses:

- `Source(turn_id, quote, role)`
- `ProofResult(kind, value, inputs, sources, recompute_ok, rendered,
  subject, scan_scope, confidence)`

The schema is intentionally scoped to COMMIT_ON_ABSTAIN proofs. It is not
for suppressors, which have no derived value or recompute check.

### `src/radiomind/core/arithmetic_hint.py`

- Extracted cashback money formatting into `_fmt_money` as the single
  source of truth.
- Added `cashback_proof_to_result(proof) -> ProofResult`.
- `maybe_cashback_commit_closure` still uses the same proof dict and the
  same gate. Its output bytes remain unchanged.

### `tests/test_proof_result_cashback_adapter.py`

Four adapter tests verify:

- The proof dict maps losslessly into `ProofResult`.
- `ProofResult.rendered` matches the live closure's committed string.
- SelfAnchor store-scan provenance survives as `Source.turn_id` and
  `scan_scope`.
- The dataclasses are frozen.

## Verification

Command:

```bash
$HOME/.radiomind-bench-venv/bin/python -m pytest \
  tests/test_cashback_commit_closure.py \
  tests/test_cashback_closure_field_9aaed6a3.py \
  tests/test_proof_result_cashback_adapter.py -q
```

Result:

```text
23 passed
```

This covers the existing 15 cashback closure tests, 4 real-field
`9aaed6a3` tests, and 4 new carrier adapter tests.

## Decision

Phase2-1b is accepted as a narrow, behavior-preserving carrier pilot.
The next useful step is Phase2-1c: add an age adapter using the same
`ProofResult` carrier. Age is the real pressure test because it needs
dual-source provenance (`at_age` + `current_age`) and carries a skill
confidence.

Do not migrate role / temporal into this carrier. If those are ever
unified, they need a separate suppressor abstraction.
