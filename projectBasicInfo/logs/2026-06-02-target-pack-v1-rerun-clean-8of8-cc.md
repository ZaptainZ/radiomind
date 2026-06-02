# target-pack v1 — infra re-run confirms required clean 8/8

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Follow-up to the infra-red baseline (`970f302`). Re-running ONLY
the two infra-failed required qids under normal network confirms they pass →
the v1 baseline's gate-red was purely transient infra, and **required is clean
8/8**. No code change.

---

## Re-run (the two infra qids only)
`run_longmemeval_mem0.py --qids bb7c3b45,c18a7dc8` (fresh sandbox,
answer=deepseek-v3.2/dashscope, judge=gpt-4o/openrouter), 847s, acc 1.000:
- `bb7c3b45` (savings) → `"You saved $300 on the Jimmy Choo heels."` — gold $300 → **PASS**
- `c18a7dc8` (age_interval) → `"7"` — gold 7 → **PASS**

Both had returned `[answer error: <urlopen DNS error>]` in the baseline run; with
the network healthy they answer correctly. This definitively confirms the
baseline classification: **transient answer-LLM infra, not regression.**

## target-pack v1 status
- **required: clean 8/8** (role, TESG suppressor, TESG negative, cashback,
  person_age, NAR + savings & age_interval now re-confirmed). 0 real regressions.
- observe: 2/2 still FAIL — expected, parked/deferred (OrderedEventList
  precision, event_cluster_interval); they never red the gate.
- The pack is now a trustworthy post-key-path-change gate (required 8/8 green
  under normal network).

## Still open (separate small fix — NOT done here)
The answer-LLM call lacks the judge's transient-error retry, so a long run can
still spuriously red a required qid on a network blip. Options (deferred):
add answer-call retry, or have `target_pack.py` auto-re-run qids whose answer
is `[answer error: …]`. Tracked, not bundled into this attribution cycle.

## Files
- this log (re-run artifact was throwaway `/tmp/tp_rerun.json`; not committed).
