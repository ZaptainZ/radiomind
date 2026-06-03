# Core Dev Experience standardization (close-out)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Docs/process only. **No runtime code changed, no benchmark run.**
Closes the stability/observability line and the formal pivot away from bench
optimization.

---

## Why now
The cohort audit established that the remaining LME-S tail is several small,
distinct mechanisms (structural floor, temporal multi-hop, aggregation breadth,
concrete overcommit, single-turn ranking), none with a cohort large enough to
justify a global change or another committer. So bench optimization is parked
and the verified-stable tool-chain is promoted to a project standard.

## What was produced
1. **New guide `projectBasicInfo/03_DEV_WORKFLOW.md`** — the operations manual:
   - the three gates and their order (regression_pack → target_pack →
     diagnose_qid), with env hard-rules;
   - a "before you change X, run Y" table (helper / retrieval / closure / skill);
   - closure/proof boundaries (committer vs suppressor, hint-only ≠ committer,
     "closure_view ready" ≠ PASS, ProofResult / commit_on_abstain / SelfAnchor /
     closure_view);
   - the "gate red → diagnose decision tree" mapping every `path_summary`
     diagnosis.layer (incl. DX-2c `concrete_wrong_bypassed_committer` /
     `proof_input_turn_missing`) to a fix direction;
   - the parked-directions table (don't reopen without new evidence).
2. **`01_PROJECT_OVERVIEW.md`** — new "Dev Experience 标准化（2026-06-02）"
   section: gates, diagnose labels, closure boundaries, parked directions, pointer
   to 03.
3. **`CLAUDE.md`** — doc index row for `03_DEV_WORKFLOW.md` so it routes as the
   "read before changing helper/retrieval/closure" entry.

## Boundary
Pure documentation/process. No change to any `src/` runtime, no change to the
gate scripts' behavior, no benchmark executed. The guide describes existing tools
as they already behave.

## State at close
Stability/observability line complete and parked. Commit chain (all pushed):
DX-2b → #3 audit → probes → c18a7dc8 fresh verify → bb7c3b45 root cause →
DX-2c → cohort audit (park) → this standardization. Knowledge mirrored to
memory + RadioHeader global topic + shortwave.

## Next (open, not started)
With dev-experience standardized, future work is product/architecture
consolidation against this baseline (public API layering, packaging, the
pluggable-memory story) — a new workstream, to be scoped explicitly when chosen.
Bench score-chasing is closed.
