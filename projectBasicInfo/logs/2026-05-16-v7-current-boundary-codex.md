# 2026-05-16 V7 current boundary analysis — Codex

## Background

User asked whether V7 is effectively finished after the latest full-answer logs.

## Goal

Reconcile the older V7 6-run scoreboard with the newer full-answer re-test and decide whether further work should continue within V7 or move to a new direction.

## Approach

- Read latest `2026-05-15-v7-fullans-final-cc.md`.
- Re-ran `bench/end_to_end/strict_judge.py` on `v7-flip10-fullans*.json`.
- Inspected final answer sections for the stable PASS, rotating PASS, and stable FAIL groups.
- Checked the latest commit `8156056`, which fixed answer truncation in `run_locomo_mem0.py` and tightened `strict_judge.py`.

## Findings

- Latest full-answer runs converge to strict `5/10` across 3 independent runs.
- The previous `5.5/10` 6-run mean was inflated by `answer[:2000]` truncation and body-match leniency.
- V7's stable gains are real but bounded: `c2 Maria`, `c3 Tilly`, and `c9 Calvin/Dave` are 3/3 PASS.
- `c1 Gina`, `c3 Nate`, and `c6 September` remain 2/3 rotating because V7 makes the correct candidate salient but does not force the final commit.
- `c2 financial`, `c3 count`, `c4 Seattle`, and `c5 Voyageurs` are 0/3 stable FAIL and require retrieval, abstraction, or counting/dedup reasoning outside the current candidate-injection mechanism.

## Conclusion

V7 evidence-candidate injection should be considered a completed local optimum: real strict gain is `+1` over V6.3, but further prompt/candidate formatting tweaks are unlikely to break past `5/10`. The next work should be a new branch/direction: either V7.1 candidate commitment hardening for the 2/3 rotating cases, or V8 retrieval/count/abstraction work for the 0/3 stable failures.
