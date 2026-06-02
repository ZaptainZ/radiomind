# DX-2a — diagnose_qid path_summary (failure-location projection)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Done (deterministic). Implements the DX-2 audit's DX-2a slice: a
derived `path_summary` that turns diagnose_qid's horizontal sections into one
failure-location path. Pure projection over existing data — NO new probes, NO
runtime change, NO LLM. DX-2b (e2e-result overlay) deferred.

---

## Change (bench/end_to_end/diagnose_qid.py only)
- `build_path_summary(rec) -> dict`: projects existing sections into
  `retrieval -> deterministic_layer (fired/refused/proofs_available) ->
  skill_route -> closure_decision (committers/suppressors) -> diagnosis`.
  Prefers `helper_proofs` + `closure_view` over raw `helper_signals`
  (per audit gap #3).
- `_classify_layer(...)`: conservative `diagnosis.layer` — only the labels the
  deterministic sections can prove: `closure_ready` (a committer would commit /
  a suppressor detected), `helper_refusal` (decisive refusal_reason),
  `proof_ready` (helper fired, hint-only), `retrieval_gap` (0 gold in top-200),
  `skill_route_gap`, else `unknown`. The answer/judge/parked/precision labels
  are intentionally LEFT to DX-2b (they need the e2e artifact).
- `_print_path_summary(...)`: one compact human block printed BEFORE the
  detailed sections.
- Wiring: `rec["path_summary"] = _safe(build_path_summary, rec)` (in the JSON);
  `_print_path_summary(...)` before `_print_summary`.

### Known DX-2a gap (audit #1, deferred)
diagnose_qid does not probe `run_list_ordering`, so `skill_route.list_ordering`
is reported as `"not_probed"` (honest placeholder) rather than fired/silent.

## Verification (deterministic, no ingest/LLM)
- `tests/test_path_summary.py` (7): closure_ready via committer-would-commit;
  closure_ready via suppressor-detected; helper_refusal (decisive reason);
  proof_ready (helper fired, no closure); retrieval_gap (0/200); unknown
  (no evidence); print doesn't crash; list_ordering reported not_probed.
- Added regression-pack category `diagnostic:path-summary`. Full pack:
  **16 categories ALL PASS**.
- syntax-clean.

## Next — DX-2b (deferred)
`--e2e-result <json>` overlay: load a saved runner artifact, and when the qid
is present add `final_answer / correct / judge_failed / helper_hints` to
`path_summary` + the `answer_or_judge_path` and `parked_or_deferred` /
`skill_precision_gap` labels. That's where target-pack red points get
explained (e.g. distinguishing `[answer error: …]` from a real
helper/closure failure).

## Files (uncommitted — pending review)
- `bench/end_to_end/diagnose_qid.py`
- `tests/test_path_summary.py` (new)
- `bench/end_to_end/regression_pack.py` (+`diagnostic:path-summary`)
- this log
