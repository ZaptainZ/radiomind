# 2026-05-15 V7 results analysis — Codex

## Background

User asked to review the new V7 logs and results after the V7 evidence-candidate series completed six LoCoMo flip-set runs.

## Goal

Determine whether V7's reported improvement over V6.3/V6.6 is real, what remains unresolved, and whether the latest scoreboard has evaluation caveats.

## Approach

- Read `2026-05-13-v7-evidence-candidates-cc.md` and `2026-05-15-v3-to-v7-scoreboard-cc.md`.
- Re-ran `bench/end_to_end/strict_judge.py` over the six V7 result JSON files.
- Inspected per-qid answer tails for stable PASS/FAIL patterns.
- Checked `run_locomo_mem0.py` result serialization and V7 evidence-candidate injection path.

## Findings

- V7 strict scores reproduce as `6, 6, 5, 6, 5, 5`, mean `5.5/10`, versus V6.3 strict `4/10` and V6.6.p2 strict `4/10`.
- V7's real architectural gain is evidence-candidate injection, especially temporal-role candidates for `c1 Gina`, `c2 Maria`, and `c6 September 2022`.
- V7 still cannot solve cases where retrieval does not surface gold-bearing memory (`c4 Seattle`, `c5 Voyageurs`) or where the answer needs deeper reasoning/dedup (`c3 big screen count`).
- Important caveat: `run_locomo_mem0.py` stores `answer[:2000]` in result JSON/checkpoint records. Many V7 answers are exactly 2000 chars, so strict re-judge may evaluate truncated reasoning text rather than the final committed answer. This can overcount marginal cases such as `c1 Gina` run 5 or `c3 Nate dragons`, where the visible reasoning mentions gold tokens but the final answer may not be preserved.

## Conclusion

V7 is directionally real and better than V6.6.p2 because it moved from prompt hints to structured answer candidates. However, the precise `5.5/10` should be treated as a strong but not final estimate until the harness stores full answers and strict judge uses the final answer section. The next reliability fix should be full-answer persistence before further model or retrieval tuning.
