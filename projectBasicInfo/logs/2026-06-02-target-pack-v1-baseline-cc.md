# target-pack v1 — first live baseline (attribution only)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: First live baseline: **no real regression found; gate red due to
2 answer-LLM infra failures.** Result attribution only — NO fixes, NO
fix-workstream opened (per instruction). (Explicitly NOT a "clean green
baseline" — this run stays labelled infra-red; a clean required-8/8 baseline
is only established after the two infra qids re-run green under normal
network.)

---

## Run
`target_pack.py` → `run_longmemeval_mem0.py --qids <10> --sandbox
/tmp/rm-sandbox-target-pack`, answer=deepseek-v3.2/dashscope,
judge=gpt-4o/openrouter. Wall time ~15527s (~4.3h). Result artifact:
`bench/end_to_end/target-pack-result.json`.

**GATE: required 6/8 PASS (FAIL), observe 0/2.**

## Per-qid attribution
| qid | line | mode | result | category |
|---|---|---|---|---|
| 031748ae_abs | role suppressor | required | PASS | — |
| gpt4_93159ced_abs | TESG suppressor | required | PASS | — |
| gpt4_93159ced | TESG negative anchor | required | PASS | — |
| 9aaed6a3 | cashback committer | required | PASS | — |
| gpt4_d12ceb0e | person_age hint | required | PASS | — |
| d851d5ba | NAR charity sum | required | PASS | — |
| **bb7c3b45** | savings hint | required | **FAIL** | **infra** (answer-LLM DNS) |
| **c18a7dc8** | age_interval committer | required | **FAIL** | **infra** (answer-LLM DNS) |
| gpt4_7abb270c | OrderedEventList | observe | FAIL | real gap, **parked** (precision) |
| b46e15ed | event_cluster_interval | observe | FAIL | real gap, **deferred** |

## Evidence for the infra classification
Both failing required qids have `answer ==
"[answer error: <urlopen error [Errno 8] nodename nor servname provided, or not
known>]"` — a DNS-resolution failure on the answer-LLM (dashscope) call during
the 4.3h run. The judge then correctly scored the error string "incorrect".
These are NOT savings/age_interval logic regressions: both are historically
known-good, and the same-batch cashback / person_age / NAR / role / TESG
required qids all passed. So **logic-wise required is 8/8; the gate FAIL is
purely two transient network errors.**

The two observe FAILs are the expected parked/deferred gaps:
- `gpt4_7abb270c`: ordered list produced but wrong order + name over-specify +
  substitution (exactly the 1g precision gap; parked).
- `b46e15ed`: pure abstain "information not enough" (event_cluster_interval
  not handled; deferred).

## Harness robustness note (recorded, NOT implemented)
The runner retries the **judge** call on transient HTTP/SSL errors (V8.2.2b)
but does NOT give the **answer-LLM** call the same retry. Over a multi-hour
run, a transient DNS/network blip therefore turns a known-good required qid
into a spurious FAIL — exactly what happened to bb7c3b45 + c18a7dc8. Options
(deferred to the user, no code changed here):
1. add the same transient-error retry to the answer-LLM call, or
2. have `target_pack.py` auto-re-run qids whose answer is `[answer error: …]`.

## Conclusion / next
- **No real regression.** All shipped closures/guards/hints that produced an
  answer behaved correctly (required logic 8/8).
- Do NOT open a fix workstream (per instruction). The infra-vs-real split is
  the deliverable.
- Suggested (authorized) follow-up: cheaply re-run ONLY the two infra-failed
  qids (`bb7c3b45,c18a7dc8`) to confirm they pass under normal network. Only
  then is the baseline clean required-8/8 (recorded in a separate follow-up
  log); this run stays the infra-red baseline. After that the pack is the
  post-key-path-change gate. Adding answer-LLM retry / auto-rerun is a
  separate small fix — NOT mixed into this attribution commit.

## Files
- `bench/end_to_end/target-pack-result.json` (baseline artifact — to commit)
- this log
