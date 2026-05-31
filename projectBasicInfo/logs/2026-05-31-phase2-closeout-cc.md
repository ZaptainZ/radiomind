# Phase 2 — Proof Carrier & Shared Commit Gate (close-out)

**Date**: 2026-05-31
**Author**: Claude Code
**Status**: Phase 2 COMPLETE and intentionally bounded. The two
commit-on-abstain closures (cashback, age) now share a proof carrier and a
single commit gate. The registry/dispatcher from the original Phase-2 sketch
was deliberately NOT built — the 1a audit proved it would over-abstract two
genuinely opposite-polarity families. role / TESG / runner unchanged
throughout. Every step was byte-path verified.

---

## What Phase 2 delivered (commits on origin/main)
| Step | Commit | Delivered |
|---|---|---|
| 1a | `19830bb` | Read-only audit of the 4 post-LLM closures; field-intersection matrix; the **two-families** finding |
| 1b | `586a50c` | `ProofResult`/`Source` carrier + cashback telemetry-only adapter (lossless) |
| 1c | `af3f6e9` | age adapter — stress-tested `sources: list` (dual provenance) + `confidence` |
| 1d | `835fb2f` | shared `commit_on_abstain`; cashback tail migrated |
| 1e | `b0c5e7b` | `is_commit_abstain_candidate` fast-bypass; age tail migrated; cashback concrete-path cost restored |

## The decisive boundary (1a, reaffirmed)
The four post-LLM rewrite closures are TWO families with **inverted abstain
polarity**:
- **COMMIT_ON_ABSTAIN** (cashback, age): fire ONLY on a pure abstain →
  upgrade to a concrete, recomputed value; never overwrite concrete.
- **SUPPRESS_OVERCOMMIT** (role `maybe_rewrite_with_guard`,
  TESG `maybe_rewrite_with_temporal_guard`): fire ONLY on a concrete
  over-commit → downgrade to an abstain; bypass when already abstaining.
  No derived value, no recompute.

A single `ProofResult → commit_closure` only fits the committer family.
Forcing the suppressors in would leave half the carrier meaningless and
collide opposite safety invariants. So Phase 2 is scoped to the committers.

## End-state architecture (committer family)
Each committer closure now:
1. runs its own domain pre-gates (cashback: trigger/merchant/amount/rate;
   age: skill/conf/computed/mode),
2. **fast-bypasses** a concrete answer via `is_commit_abstain_candidate`
   BEFORE resolving its proof (resolve is read-only but can store-scan),
3. resolves its domain proof and builds a `ProofResult` via its adapter
   (`cashback_proof_to_result` / `age_interval_proof_to_result`),
4. commits via the single shared `commit_on_abstain(proof, llm_answer)`
   (pure-abstain + complete proof + `recompute_ok` → `proof.rendered`).

Shared pieces (`src/radiomind/core/proof_result.py`):
- `Source(turn_id, quote, role)` — list-valued provenance (age dual,
  cashback rate-only/split).
- `ProofResult(kind, value, inputs, sources, recompute_ok, rendered,
  subject, scan_scope, confidence)` — the audited age∩cashback intersection.
- `is_commit_abstain_candidate(llm_answer)` — cheap pre-check.
- `commit_on_abstain(proof, llm_answer)` — the one gate.

The `SelfAnchorProof` (`self_anchor.py`) remains the store-scan proof; both
adapters fold its `source_turn_id`/`scan_scope` into `Source`/`scan_scope`.

## Decision: stop abstracting here (no registry, no dispatcher)
- The runner (`run_longmemeval_mem0.py`) keeps calling the four closures
  directly, in order. This is clearer and safer than a dispatcher: ordering
  is explicit, the suppressor↔committer polarity split stays visible, and
  there is no central indirection to reason about.
- A unified registry would have to special-case the two polarities anyway,
  re-introducing the complexity it claims to remove.
- savings / person_age are **hint-only** today (no commit closure); they are
  NOT carrier candidates. If one ever gains a commit-on-abstain closure, the
  carrier is ready — but only add it on real evidence of a trust-gap
  (the 1c principle: deterministic real-data proof, not stochastic).

## Verification posture
Every migration was gated on the committer + carrier + self_anchor suite
staying byte-identical (1b 23 → 1c 61 → 1d/1e 104–105 passed, exact-output
closure tests pinning the committed bytes). No behavior or output changed in
any step; only structure was centralized.

## Process notes (for future migrations in this repo)
- Edit anchors must match the file's EXACT formatting — a multi-line vs
  compact `return (...)` mismatch silently no-ops the Edit; verify with grep
  after each closure edit (a 1d migration appeared "done" but had not taken).
- The Edit tool only treats a file as "read" when read via the Read tool —
  reading via Bash `cat`/`awk` does NOT satisfy it (a 1c edit failed for this).
- Bench env: use `~/.radiomind-bench-venv/bin/python` (py3.13); see
  [[project-bench-venv-local-disk]].

## Status
Phase 2 closed. No follow-up planned. The proof carrier + shared gate are in
production for both committers; suppressors and hints are out of scope by
design.
