# DX-2b: diagnose_qid `--e2e-result` final-answer overlay

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Implemented + tested (15 path_summary tests, full regression pack
16/16 ALL PASS). Awaiting user review before commit.

---

## Goal

Close gap #2 from the diagnostic-UX read-only audit
(`2026-06-02-diagnostic-ux-standard-output-audit-codex.md`): DX-2a produced a
deterministic `path_summary`, but it could not see the *actual* e2e final
answer, so a red target-pack qid still required hand-opening the runner
artifact to tell a real logic gap from an answer-LLM / judge infra failure.

DX-2b overlays a saved `run_longmemeval_mem0` result onto `path_summary` so a
red qid auto-attributes to the answer-or-judge path.

## What changed (`bench/end_to_end/diagnose_qid.py`)

- `build_path_summary(rec, e2e=None)` — new optional `e2e` per_query record.
  When present, attaches `path_summary["final_answer"]` and reclassifies
  `diagnosis.layer` via the overlay (below).
- `_extract_final(e2e)` — projects the runner's per_query fields
  (`answer` / `correct` / `judge_failed` / `helper_hints.answer_pure_abstain`)
  into `{answer(160), correct, judge_failed, answer_error, pure_abstain,
  helper_hints}`. `answer_error` = answer string starts with `[answer error`.
- `_overlay_e2e(det_layer, det_reason, final)` — reclassification, in priority:
  1. `answer_error` → `answer_or_judge_path` (infra/transient, not logic)
  2. `judge_failed` → `answer_or_judge_path` (verdict unreliable)
  3. `correct` → `pass`
  4. wrong + deterministic layer was `closure_ready` → `answer_or_judge_path`
     (proof was ready, answer-LLM ignored it = trust-gap)
  5. otherwise keep the deterministic label (retrieval_gap / helper_refusal /…)
- `_load_e2e_record(path, qid)` — finds the qid's record in a saved result
  json's `per_query` list (matches `question_id` or `qid`). Returns None if the
  file/qid is absent; the overlay is strictly optional.
- `_print_path_summary` — prints an `e2e answer:` line with verdict +
  ANSWER-ERROR / JUDGE-FAILED / pure-abstain flags when `final_answer` present.
- `main()` — `--e2e-result <json>` flag; loads the record, warns (non-fatal) if
  the qid isn't in the file, passes it through `_safe(build_path_summary, rec,
  e2e_rec)`.

## Boundary kept

Pure projection — no new probes, no LLM, no runtime/runner behaviour change.
The overlay only *reads* a saved artifact. No dispatcher, no new helper/closure.
`diagnosis.layer` priority preserves DX-2a's deterministic labels; e2e only
overrides toward `pass` / `answer_or_judge_path`.

## Verification

- `tests/test_path_summary.py` +8 (now 15): correct→pass; answer_error→
  answer_or_judge_path; judge_failed→answer_or_judge_path; wrong+closure_ready→
  answer_or_judge_path (trust-gap, pure_abstain flagged); wrong+retrieval_gap
  keeps retrieval_gap; no-e2e omits final_answer; `_load_e2e_record` matches by
  question_id / returns None on miss; print-with-final-answer doesn't crash.
- Real-artifact sanity (no ingest): `_load_e2e_record` + `_extract_final` on
  `aas2-c18a7dc8-e2e.json` — fields line up
  (`question_id/answer/correct/judge_failed`), extraction correct.
- Full `regression_pack.py`: **16 categories ALL PASS** (`diagnostic:path-
  summary` 15 passed).

## Files
- `bench/end_to_end/diagnose_qid.py` (overlay + flag + loader)
- `tests/test_path_summary.py` (+8 DX-2b tests)
- (regression pack already lists `diagnostic:path-summary` from DX-2a)

## Usage
```
python bench/end_to_end/diagnose_qid.py --qid 9aaed6a3 \
    --e2e-result bench/end_to_end/target-pack-result.json
```
Red target-pack qid → `path_summary.diagnosis.layer` directly says whether the
failure is `answer_or_judge_path` (infra/trust-gap) or a deterministic gap.
